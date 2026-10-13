"""Luminaire interface: DALI-2 / D4i two-channel driver, 0-10 V legacy sink,
16 A normally-closed relay (Sections 5.2 "Failure below the controller", 6.1).

The relay coil is energised only to switch the light *off*, so a dead node
or lost control power leaves the light on. When the controller stops writing
to the bus, the driver falls to its stored system-failure level: the road
class's 22:00 level, or 60 % on a High-Injury Network segment if that is
higher. A dead node is a slightly over-lit light, never a dark one.

The metering model stands in for the VDL-7's metering IC so the controller's
driver-fault and day-burner alarms have something to watch.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

from .profiles import HIN_FLOOR, ClassProfile, Phase

STANDBY_W = 0.5           # driver standby draw with the relay closed and output off
BUS_TIMEOUT_S = 5.0       # controller silent this long -> system-failure level


def failure_level(profile: ClassProfile, hin: bool, hin_floor: int = HIN_FLOOR) -> float:
    return float(max(profile.base(Phase.STEP), hin_floor if hin else 0))


@dataclass
class LuminaireDriver:
    system_failure_level: float = 60.0       # % of design, written at commissioning
    interface: str = "dali2"                 # "dali2" (D4i, 2 ch) or "0-10v"
    relay_closed: bool = True                # NC: closed = light powered
    white: float = 0.0                       # % drive, channel 1 (pins 4-5)
    amber: float = 0.0                       # % drive, channel 2 (pins 6-7)
    controller_alive: bool = True
    last_write_mono: float = -math.inf
    fault: Optional[str] = None              # None | "open_circuit" | "stuck_on"
    history: list = field(default_factory=list, repr=False)

    @classmethod
    def commissioned_for(cls, profile: ClassProfile, hin: bool = False, interface: str = "dali2") -> "LuminaireDriver":
        return cls(system_failure_level=failure_level(profile, hin), interface=interface)

    def set(self, white: float, amber: float, relay_on: bool, mono: Optional[float] = None) -> None:
        """Called by the controller every loop pass."""
        self.controller_alive = True
        if mono is not None:
            self.last_write_mono = mono
        self.relay_closed = bool(relay_on)
        white = max(0.0, min(100.0, white))
        amber = max(0.0, min(100.0, amber))
        if self.interface == "0-10v":          # one channel on legacy drivers
            self.white, self.amber = min(100.0, white + amber), 0.0
        else:
            self.white, self.amber = white, amber

    def watchdog(self, mono: float, timeout_s: float = BUS_TIMEOUT_S) -> bool:
        """Driver side of the bus: no write for `timeout_s` means the node is
        dead or hung. Returns True if the driver fell to its failure level."""
        if self.controller_alive and mono - self.last_write_mono > timeout_s:
            self.controller_lost()
            return True
        return False

    def controller_lost(self) -> None:
        """Bus silent / control power lost: system-failure level, relay NC."""
        self.controller_alive = False
        self.relay_closed = True
        self.white, self.amber = self.system_failure_level, 0.0

    def control_power_lost(self) -> None:
        """Loss of control power de-energises the coil; NC contact closes."""
        self.controller_lost()

    @property
    def output_pct(self) -> float:
        """Delivered drive as % of design output (both channels)."""
        if self.fault == "open_circuit":
            return 0.0
        if self.fault == "stuck_on":
            return 100.0
        return (self.white + self.amber) if self.relay_closed else 0.0

    @property
    def channels(self) -> Tuple[float, float]:
        if self.fault:
            out = self.output_pct
            return (out, 0.0)
        return (self.white, self.amber) if self.relay_closed else (0.0, 0.0)

    def measured_w(self, design_w: float) -> float:
        """What the metering IC reads at the luminaire feed."""
        if self.fault == "stuck_on":
            return design_w + STANDBY_W
        if not self.relay_closed:
            return 0.0
        if self.fault == "open_circuit":
            return STANDBY_W
        return STANDBY_W + design_w * (self.white + self.amber) / 100.0
