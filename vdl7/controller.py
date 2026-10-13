"""The VDL-7 control loop (Section 2.4), mode ladder and SAFE-mode clock
(Section 5), flash store with two bundle banks and a checkpoint (Section 5.1).

The node, not the CMS, owns the curfew. Everything the loop needs to dim on
time lives on the node: an astronomical clock, the DST rule, a signed profile
bundle and an event store. A cellular or cloud outage changes only *which
events arrive*, never whether the lights dim.

Reference implementation in Python, structured to port to C on a Cortex-M33:
no allocation in the loop beyond the output record, no wall-clock reads
outside `tick`, every timer in node-monotonic seconds.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Tuple

from .clock import (DC_LAT, DC_LON, NIGHT_ELEVATION_DEG, Photocell, RtcHoldover,
                    learned_night, local_hour, solar_elevation_deg, to_local)
from .driver import LuminaireDriver
from .events import Event, EventKind, EventStore, Priority
from .profiles import (BOOST_MIX, ClassProfile, Phase, ProfileBundle, RoadClass,
                       clo_factor, default_bundle, phase_for_hour)
from .security import SignedMessage, Verifier


class Mode(str, Enum):
    ONLINE = "ONLINE"            # backhaul heard within 15 min
    MESH = "MESH"                # backhaul silent, gateway reachable over Wi-SUN
    AUTONOMOUS = "AUTONOMOUS"    # no backhaul, no gateway, RTC trusted
    SAFE = "SAFE"                # clock lost: photocell + learned dark midpoint


@dataclass
class NodeConfig:
    node_id: str
    road: RoadClass
    lat: float = DC_LAT
    lon: float = DC_LON
    hin: bool = False                     # Vision Zero High-Injury Network segment
    segment_id: str = "seg-0"
    tunable_white: bool = False           # dual-channel 2700K + PC-Amber engine
    burn_hours: float = 0.0
    backhaul_timeout_s: float = 900.0
    gateway_timeout_s: float = 900.0
    loop_max_age_s: float = 900.0
    slew_up_pct_s: float = 25.0
    slew_down_pct_s: float = 1.0
    checkpoint_interval_s: float = 60.0
    night_elevation_deg: float = NIGHT_ELEVATION_DEG


@dataclass
class Checkpoint:
    """Written to flash every 60 s. What SAFE mode has to work with."""
    learned_midpoint_h: float = 1.17      # factory seed: DC solar midnight, EDT
    prev_night_len_h: float = 11.0
    learned: bool = False                 # replaced by a clocked night yet?
    night_hour: Optional[float] = None    # local hour at last write (or SAFE estimate)
    lit: bool = False
    written_mono: float = 0.0
    bundle_version: int = 0


class Flash:
    """Two signed bundle banks with a monotonic version, plus the checkpoint.
    Shared between a controller and its reboot."""

    def __init__(self, bundle: Optional[ProfileBundle] = None):
        self.banks: List[Optional[Tuple[bytes, bytes]]] = [None, None]
        self.active: int = 0
        self.checkpoint = Checkpoint()
        self._bundle: ProfileBundle = bundle or default_bundle(version=0)
        self.install_log: List[str] = []

    @property
    def bundle(self) -> ProfileBundle:
        return self._bundle

    @property
    def version(self) -> int:
        return self._bundle.version

    def install(self, msg: SignedMessage, verifier: Verifier) -> bool:
        """Verify, check the monotonic version, write the inactive bank, switch."""
        if not verifier.verify(msg.payload, msg.signature):
            self.install_log.append("REJECT bad signature")
            return False
        d = msg.decode()
        if d.get("kind") != "bundle":
            self.install_log.append("REJECT not a bundle")
            return False
        new = ProfileBundle.from_dict(d)
        if new.version <= self._bundle.version:
            self.install_log.append(f"REJECT version {new.version} <= {self._bundle.version}")
            return False
        inactive = 1 - self.active
        self.banks[inactive] = (msg.payload, msg.signature)
        self.active = inactive
        self._bundle = new
        self.checkpoint.bundle_version = new.version
        self.install_log.append(f"INSTALL v{new.version} bank {inactive}")
        return True


@dataclass
class Output:
    mono: float
    mode: Mode
    lit: bool
    phase: Phase
    hour: Optional[float]
    base: int
    activity: float
    target: float
    level: float
    drive: float
    white: float
    amber: float
    reasons: List[str] = field(default_factory=list)


class VDL7Controller:
    """One pole. Call the input methods as things happen, then `tick` at 1 Hz."""

    def __init__(self, cfg: NodeConfig, flash: Flash, rtc: RtcHoldover, verifier: Verifier,
                 driver: Optional[LuminaireDriver] = None, photocell: Optional[Photocell] = None):
        self.cfg = cfg
        self.flash = flash
        self.rtc = rtc
        self.verifier = verifier
        self.driver = driver or LuminaireDriver.commissioned_for(self.profile)
        self.photocell = photocell or Photocell()
        self.events = EventStore()
        self.mode = Mode.SAFE
        self.level = 0.0
        self.output: Optional[Output] = None
        self.log: List[str] = []
        # timers, all node-monotonic
        self._boot_mono: Optional[float] = None
        self._last_backhaul = -math.inf
        self._last_gateway = -math.inf
        self._presence_until = -math.inf
        self._carpet_until = -math.inf
        self._loop: Optional[Tuple[float, float]] = None     # (veh/15 min, received mono)
        self._last_checkpoint = -math.inf
        # astronomical learning
        self._astro_prev: Optional[bool] = None
        self._astro_dusk_local: Optional[datetime] = None
        self._seeded = False
        # SAFE-mode anchors
        self._pc_dusk_mono: Optional[float] = None
        self._safe_anchor: Optional[Tuple[float, float]] = None   # (hour, mono)
        self._mesh_reachable = False

    # ------------------------------------------------------------------ inputs
    @property
    def profile(self) -> ClassProfile:
        return self.flash.bundle.profiles[self.cfg.road]

    def backhaul_hello(self, mono: float, utc: Optional[datetime] = None) -> None:
        """CMS heartbeat over cellular; carries LwM2M time when present."""
        self._last_backhaul = mono
        if utc is not None:
            self.rtc.sync(mono, utc)

    def gnss_fix(self, mono: float, utc: datetime) -> None:
        self.rtc.sync(mono, utc)

    def mesh_gateway_seen(self, mono: float) -> None:
        """Mesh layer reports a path to a node with live backhaul."""
        self._last_gateway = mono

    def radar_detect(self, mono: float, cls: str = "pedestrian") -> None:
        self._presence_until = mono + self.flash.bundle.presence_hold_s

    def carpet_event(self, mono: float) -> None:
        """Neighbour detection relayed over the mesh (3 hops, 60 s hold)."""
        self._carpet_until = mono + self.flash.bundle.carpet_hold_s

    def photocell_sample(self, lx: float, mono: float) -> None:
        flip = self.photocell.sample(lx, mono)
        if flip is True:                      # light -> dark: dusk observed
            self._pc_dusk_mono = mono
            self._safe_anchor = None
        elif flip is False:                   # dark -> light: dawn observed
            self._pc_dusk_mono = None
            self._safe_anchor = None

    def receive(self, msg: SignedMessage, mono: float, via: str = "backhaul") -> bool:
        """Any signed message from the CMS, directly or relayed by the mesh.
        Relays never re-sign, so the same bytes verify everywhere."""
        if not self.verifier.verify(msg.payload, msg.signature):
            self.log.append(f"{mono:.0f} REJECT unsigned/forged message via {via}")
            return False
        d = msg.decode()
        kind = d.get("kind")
        if via == "backhaul":
            self._last_backhaul = mono
        if kind == "bundle":
            return self.flash.install(msg, self.verifier)
        if kind == EventKind.CANCEL.value:
            return self.events.cancel(str(d.get("target", "")))
        ev = Event.from_dict(d)
        ev.via = via
        if ev.kind == EventKind.LOOP_VOLUME:
            self._loop = (float(ev.payload.get("veh15", 0.0)), mono)
        self.events.put(ev, mono)
        return True

    def set_loop_volume(self, veh15: float, mono: float) -> None:
        """Convenience for benches; the CMS normally sends a signed event."""
        self._loop = (veh15, mono)

    # ---------------------------------------------------------------- helpers
    def _seed_learning(self, utc: datetime) -> None:
        """First trusted tick: compute tonight's dark midpoint from the astro
        clock so SAFE mode has a current value even before a full clocked night."""
        cp = self.flash.checkpoint
        if cp.learned:
            return
        loc = to_local(utc)
        d = loc.date() if loc.hour >= 12 else (loc - timedelta(days=1)).date()
        mid, length = learned_night(self.cfg.lat, self.cfg.lon, d)
        cp.learned_midpoint_h, cp.prev_night_len_h, cp.learned = mid, length, True

    def _learn_night(self, utc: datetime, astro_night: bool) -> None:
        """Track dusk and dawn transitions on the astro clock and re-learn the
        dark midpoint and night length after each clocked night."""
        if self._astro_prev is None:
            self._astro_prev = astro_night
            return
        if astro_night and not self._astro_prev:
            self._astro_dusk_local = to_local(utc)
        elif (not astro_night) and self._astro_prev and self._astro_dusk_local is not None:
            dawn = to_local(utc)
            length = (dawn - self._astro_dusk_local).total_seconds() / 3600.0
            dusk_h = self._astro_dusk_local.hour + self._astro_dusk_local.minute / 60.0
            cp = self.flash.checkpoint
            cp.learned_midpoint_h = (dusk_h + length / 2.0) % 24.0
            cp.prev_night_len_h = length
            cp.learned = True
        self._astro_prev = astro_night

    def _safe_night_hour(self, mono: float) -> Optional[float]:
        """Night-hour estimate with no wall clock (Section 5.3 step 5):
        learned midpoint + (time since dusk - previous night length / 2).
        A dusk seen by the photocell this boot is the anchor; failing that,
        the flash checkpoint written before the reboot."""
        cp = self.flash.checkpoint
        if self._pc_dusk_mono is not None:
            dusk_hour = (cp.learned_midpoint_h - cp.prev_night_len_h / 2.0) % 24.0
            return (dusk_hour + (mono - self._pc_dusk_mono) / 3600.0) % 24.0
        if self._safe_anchor is None and self.photocell.dark and cp.night_hour is not None and cp.lit:
            self._safe_anchor = (cp.night_hour, self._boot_mono if self._boot_mono is not None else mono)
        if self._safe_anchor is not None:
            h0, m0 = self._safe_anchor
            return (h0 + (mono - m0) / 3600.0) % 24.0
        return None

    def _write_checkpoint(self, mono: float, hour: Optional[float], lit: bool) -> None:
        cp = self.flash.checkpoint
        cp.night_hour, cp.lit, cp.written_mono = hour, lit, mono
        cp.bundle_version = self.flash.version
        self._last_checkpoint = mono

    def _emergency_active(self, mono: float) -> Optional[Event]:
        return self.events.latest(EventKind.EMERGENCY, mono)

    # ------------------------------------------------------------------- loop
    def tick(self, mono: float, dt: float = 1.0) -> Output:
        cfg, bundle, prof = self.cfg, self.flash.bundle, self.profile
        if self._boot_mono is None:
            self._boot_mono = mono
        reasons: List[str] = []

        # 1. Mode from backhaul age, gateway age and clock trust
        trusted = self.rtc.trusted(mono)
        utc = self.rtc.utc_now(mono) if trusted else None
        if not trusted:
            mode = Mode.SAFE
        elif mono - self._last_backhaul <= cfg.backhaul_timeout_s:
            mode = Mode.ONLINE
        elif mono - self._last_gateway <= cfg.gateway_timeout_s:
            mode = Mode.MESH
        else:
            mode = Mode.AUTONOMOUS
        if mode != self.mode:
            self.log.append(f"{mono:.0f} MODE {self.mode.value} -> {mode.value}")
        self.mode = mode
        self.events.purge(mono)

        # 2. Lit or not. Astro night on the node's own clock OR photocell dark.
        #    The photocell can switch lights on early but never hold them off.
        pc_dark = bool(self.photocell.dark)
        if utc is not None:
            if not self._seeded:
                self._seed_learning(utc)
                self._seeded = True
            hour: Optional[float] = local_hour(utc)
            astro_night = solar_elevation_deg(cfg.lat, cfg.lon, utc) < cfg.night_elevation_deg
            self._learn_night(utc, astro_night)
            lit = astro_night or pc_dark
            if pc_dark and not astro_night:
                reasons.append("PHOTOCELL_EARLY")
            if astro_night and not pc_dark:
                reasons.append("PHOTOCELL_VETOED")
        else:
            lit = pc_dark
            hour = self._safe_night_hour(mono) if lit else None
            reasons.append("SAFE_CLOCK" if hour is not None else "SAFE_NO_ANCHOR")

        # 3. Phase -> base level
        phase = phase_for_hour(hour) if hour is not None else Phase.STEP
        base = prof.base(phase)

        # 4. Activity in [0, 1]
        activity = 0.0
        if self._loop is not None and prof.design_volume and (mono - self._loop[1]) <= cfg.loop_max_age_s:
            activity = min(1.0, max(0.0, self._loop[0] / prof.design_volume))
            if activity > 0:
                reasons.append("LOOP")
        presence = mono < self._presence_until
        carpet = mono < self._carpet_until
        if presence or carpet:
            activity = max(activity, 1.0 if prof.occupancy else 0.5)
            reasons.append("PRESENCE" if presence else "CARPET")

        # 5. Raise toward the boost cap
        target = float(base)
        if activity > 0:
            target += (prof.boost_cap - target) * activity

        # 6. Weather: rain +15 up to the cap; fog and snow nothing (logged)
        if self.events.latest(EventKind.RAIN, mono) is not None:
            target = min(float(prof.boost_cap), target + bundle.rain_boost)
            reasons.append("RAIN")
        if self.events.latest(EventKind.FOG, mono) is not None:
            reasons.append("FOG_NO_BOOST")
        if self.events.latest(EventKind.SNOW, mono) is not None:
            reasons.append("SNOW_NO_BOOST")

        # 7. Floor: class floor, HIN floor
        floor = max(prof.floor, bundle.hin_floor if cfg.hin else 0)
        if target < floor:
            target = float(floor)
            reasons.append("FLOOR_HIN" if (cfg.hin and floor == bundle.hin_floor) else "FLOOR")

        # 8. Emergency geofence
        emergency = self._emergency_active(mono)
        if emergency is not None:
            target = 100.0
            reasons.append(f"EMERGENCY:{emergency.id}")

        # 9. Override: highest priority wins; only incident command beats an emergency
        ov = self.events.highest_priority(EventKind.OVERRIDE, mono)
        if ov is not None and (emergency is None or ov.priority >= Priority.INCIDENT_COMMAND):
            target = float(ov.payload.get("level", target))
            reasons.append(f"OVERRIDE:{ov.id}:p{int(ov.priority)}")
        elif ov is not None:
            reasons.append(f"OVERRIDE_BLOCKED_BY_EMERGENCY:{ov.id}")

        if not lit:
            target = 0.0

        # 10. Slew: up 25 %/s, down 1 %/s
        delta = target - self.level
        self.level += max(-cfg.slew_down_pct_s * dt, min(cfg.slew_up_pct_s * dt, delta))
        self.level = max(0.0, min(100.0, self.level))

        # 11. Constant light output
        drive = min(100.0, self.level * clo_factor(cfg.burn_hours))

        # Tunable white (Section 4.3): mix follows phase; presence or emergency -> white
        if cfg.tunable_white:
            mix = BOOST_MIX if (presence or carpet or emergency is not None) else bundle.mix[phase]
        else:
            mix = (100, 0)
        white = drive * mix[0] / 100.0
        amber = drive * mix[1] / 100.0

        # 12. Output, checkpoint, hour meter
        relay_on = lit or self.level > 0.5          # let the dawn fade finish
        self.driver.set(white, amber, relay_on)
        if mono - self._last_checkpoint >= cfg.checkpoint_interval_s:
            self._write_checkpoint(mono, hour, lit)
        if lit:
            cfg.burn_hours += dt / 3600.0
        reasons.insert(0, f"MODE_{mode.value}")
        reasons.insert(1, f"PHASE_{phase.value.upper()}")
        self.output = Output(mono, mode, lit, phase, hour, base, activity, target, self.level,
                             drive, white, amber, reasons)
        return self.output

    # ------------------------------------------------------------------ power
    def reboot(self) -> "VDL7Controller":
        """A new controller instance on the same flash, RTC and driver. RAM
        state (events, timers, slew level) is gone; the checkpoint is not."""
        return VDL7Controller(self.cfg, self.flash, self.rtc, self.verifier, self.driver,
                              Photocell(self.photocell.on_lx, self.photocell.off_lx, self.photocell.debounce_s))
