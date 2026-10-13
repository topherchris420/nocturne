"""Luminaire interface: DALI-2 / D4i two-channel driver, 0-10 V legacy sink,
16 A normally-closed relay (Section 5.2 "Failure below the controller").

The relay coil is energised only to switch the light *off*, so a dead node
or lost control power leaves the light on. When the DALI bus goes quiet the
driver falls to its stored system-failure level, which commissioning sets to
the road class's 22:00 level: a dead node is a slightly over-lit light, never
a dark one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from .profiles import ClassProfile, Phase


@dataclass
class LuminaireDriver:
    system_failure_level: float = 60.0       # % of design, set at commissioning
    interface: str = "dali2"                 # "dali2" (D4i, 2 ch) or "0-10v"
    relay_closed: bool = True                # NC: closed = light powered
    white: float = 0.0                       # % drive, channel 1 (pins 4-5)
    amber: float = 0.0                       # % drive, channel 2 (pins 6-7)
    controller_alive: bool = True
    history: list = field(default_factory=list, repr=False)

    @classmethod
    def commissioned_for(cls, profile: ClassProfile, interface: str = "dali2") -> "LuminaireDriver":
        return cls(system_failure_level=float(profile.base(Phase.STEP)), interface=interface)

    def set(self, white: float, amber: float, relay_on: bool) -> None:
        """Called by the controller every loop pass."""
        self.controller_alive = True
        self.relay_closed = bool(relay_on)
        if self.interface == "0-10v":          # single channel on legacy drivers
            self.white, self.amber = min(100.0, white + amber), 0.0
        else:
            self.white, self.amber = max(0.0, min(100.0, white)), max(0.0, min(100.0, amber))

    def controller_lost(self) -> None:
        """Watchdog expired / DALI bus silent: system-failure level, relay NC."""
        self.controller_alive = False
        self.relay_closed = True
        self.white, self.amber = self.system_failure_level, 0.0

    def control_power_lost(self) -> None:
        """Loss of control power de-energises the coil; NC contact closes."""
        self.controller_lost()

    @property
    def output_pct(self) -> float:
        """Delivered drive as % of design output (both channels)."""
        return (self.white + self.amber) if self.relay_closed else 0.0

    @property
    def channels(self) -> Tuple[float, float]:
        return (self.white, self.amber) if self.relay_closed else (0.0, 0.0)
