"""The VDL-7 control loop (Section 2.4), mode ladder and SAFE-mode clock
(Sections 5.2, 5.3), flash with two signed bundle banks and a checkpoint
(Section 5.1), and the node-side alarms and metering (Sections 5.1, 6.1).

The node, not the CMS, owns the curfew. Everything the loop needs to dim on
time lives on the node: an astronomical clock, the DST rule, a signed profile
bundle and an event store. A cellular or cloud outage changes only *which
events arrive*, never whether the lights dim.

Reference implementation in Python, structured to port to C on a Cortex-M33:
fixed-size state, no wall-clock reads outside `tick` and `receive`, every
timer in node-monotonic seconds.

Two deliberate departures from the letter of the spec, both safety fixes:

* Step 5 and 6 never lower the light. Where a class's evening level is above
  its boost cap (local 80 vs 70, collector 100 vs 90, park 60 vs 50), the
  spec's `base + (cap - base) x A` would dim the street when someone walks
  in. Here `target = max(base, ...)`; the spec text needs the same clamp.
* SAFE mode resumes from the flash checkpoint only when the RTC counter
  survived the outage and can say how long the power was off. If the RTC was
  reset, the node holds the 22:00 level until its photocell sees dusk.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Deque, Dict, List, Optional, Tuple

from .clock import (DC_LAT, DC_LON, NIGHT_ELEVATION_DEG, POSIX_TZ, Photocell, RtcHoldover,
                    learned_night, local_hour, night_bounds, parse_posix_tz, solar_elevation_deg, to_local)
from .driver import STANDBY_W, LuminaireDriver, failure_level
from .events import Event, EventKind, EventStore, Priority, ReplayWindow, addressed_to
from .profiles import (BOOST_MIX, PHASE_ORDER, ClassProfile, Phase, ProfileBundle, RoadClass, bundle_expired,
                       clo_factor, default_bundle, phase_for_hour, validate_bundle)
from .security import SignedMessage, Verifier


class Mode(str, Enum):
    ONLINE = "ONLINE"            # backhaul heard within 15 min
    MESH = "MESH"                # backhaul silent, gateway reachable over Wi-SUN
    AUTONOMOUS = "AUTONOMOUS"    # no backhaul, no gateway, RTC trusted
    SAFE = "SAFE"                # clock lost: photocell + learned dark midpoint


LOOP_MODES = (Mode.ONLINE, Mode.MESH)      # Section 5.2: no loop boost in AUTONOMOUS or SAFE
STALE_SKEW_S = 300.0                       # 5-min clock error budget
TILT_ALARM_DEG = 2.0                       # Section 6.1
METER_SLOT_S = 900.0                       # 15-min metering
METER_BUFFER_SLOTS = 96 * 7                # a week offline
LEARN_GATE_S = 45 * 60                     # a photocell dusk/dawn this far from the sun's is weather
PHOTOCELL_FAULT_S = 3 * 3600               # lit by the photocell in daylight this long: stuck dark
LOG_LINES = 256


@dataclass
class NodeConfig:
    node_id: str
    road: RoadClass
    lat: float = DC_LAT
    lon: float = DC_LON
    tz: str = POSIX_TZ                    # the city's POSIX TZ rule (vdl7.sites has presets)
    zone: Optional[str] = None            # neighbourhood overlay in the bundle (dark-sky buffer, nightlife...)
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
    learned_midpoint_h: float = 1.17      # factory seed: DC dark midpoint, EDT
    prev_night_len_h: float = 11.0
    learned: bool = False                 # replaced by a clocked night yet?
    night_hour: Optional[float] = None    # local hour at last write (or SAFE estimate)
    lit: bool = False
    rtc_epoch: int = -1                   # RTC counter identity at last write
    rtc_raw: float = 0.0                  # RTC counter at last write
    bundle_version: int = 0
    tilt_baseline: Optional[float] = None # commissioning accelerometer reading
    burn_hours: float = 0.0               # LED hour meter for CLO


class Flash:
    """Two signed bundle banks with a monotonic version, the checkpoint and
    the top of the anti-replay window. `image()` is what survives a reboot;
    `Flash.boot()` re-verifies it the way the MCU does at power-up."""

    def __init__(self, bundle: Optional[ProfileBundle] = None):
        self.banks: List[Optional[Tuple[bytes, bytes]]] = [None, None]
        self.active: int = 0
        self.checkpoint = Checkpoint()
        self.replay_hi: int = 0
        self._bundle: ProfileBundle = bundle or default_bundle(version=0)
        self.version_floor: int = self._bundle.version    # anti-rollback counter (secure element)
        self.outbox: Deque[dict] = deque(maxlen=METER_BUFFER_SLOTS)   # unacknowledged uplink records
        self.outbox_seq: int = 0
        self.install_log: List[str] = []

    @property
    def bundle(self) -> ProfileBundle:
        return self._bundle

    @property
    def version(self) -> int:
        return self._bundle.version

    def install(self, msg: SignedMessage, verifier: Verifier, today: Optional[date] = None) -> bool:
        """Verify, decode, bounds-check, check version and validity, write the
        inactive bank, then switch. Any failure leaves the active bank alone."""
        if not verifier.verify(msg.payload, msg.signature):
            self.install_log.append("REJECT bad signature")
            return False
        try:
            d = msg.decode()
            if not isinstance(d, dict) or d.get("kind") != "bundle":
                self.install_log.append("REJECT not a bundle")
                return False
            new = ProfileBundle.from_dict(d)
            errs = validate_bundle(new)
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError) as e:
            self.install_log.append(f"REJECT malformed bundle: {e!r}")
            return False
        if errs:
            self.install_log.append("REJECT invalid bundle: " + "; ".join(errs))
            return False
        floor = max(self._bundle.version, self.version_floor)
        if new.version <= floor:
            self.install_log.append(f"REJECT version {new.version} <= {floor}")
            return False
        if today is not None and bundle_expired(new, today):
            self.install_log.append(f"REJECT bundle v{new.version} issued {new.issued}: expired or not yet valid")
            return False
        inactive = 1 - self.active
        self.banks[inactive] = (msg.payload, msg.signature)
        self.active = inactive
        self._bundle = new
        self.version_floor = new.version
        self.checkpoint.bundle_version = new.version
        self.install_log.append(f"INSTALL v{new.version} bank {inactive}")
        return True

    # ------------------------------------------------------- persistence
    def image(self) -> dict:
        return {"banks": list(self.banks), "active": self.active, "checkpoint": replace(self.checkpoint),
                "replay_hi": self.replay_hi, "version_floor": self.version_floor,
                "outbox": [dict(r) for r in self.outbox], "outbox_seq": self.outbox_seq}

    @classmethod
    def boot(cls, image: dict, verifier: Verifier) -> "Flash":
        """Power-up: load the active bank if it still verifies and validates,
        else the other bank, else the factory profile."""
        f = cls()
        f.banks = list(image["banks"])
        f.checkpoint = replace(image["checkpoint"])
        f.replay_hi = int(image["replay_hi"])
        f.version_floor = int(image.get("version_floor", 0))     # survives even a factory fallback
        f.outbox.extend(dict(r) for r in image.get("outbox", []))
        f.outbox_seq = int(image.get("outbox_seq", 0))
        order = [image["active"], 1 - image["active"]]
        for bank in order:
            entry = f.banks[bank]
            if entry is None:
                continue
            payload, sig = entry
            if not verifier.verify(payload, sig):
                f.install_log.append(f"BOOT bank {bank} signature bad")
                continue
            try:
                b = ProfileBundle.from_dict(SignedMessage(payload, sig).decode())
                bad = validate_bundle(b)
            except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
                f.install_log.append(f"BOOT bank {bank} malformed")
                continue
            if bad:
                f.install_log.append(f"BOOT bank {bank} invalid")
                continue
            f.active, f._bundle = bank, b
            f.install_log.append(f"BOOT v{b.version} from bank {bank}")
            return f
        f.install_log.append("BOOT factory profile v0")
        return f


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
    alarms: Tuple[str, ...] = ()


@dataclass
class AuditRecord:
    """Section 5.4: the node logs who, when and why for every override."""
    mono: float
    utc: Optional[str]
    event_id: str
    level: float
    priority: int
    by: str
    reason: str
    action: str = "applied"


class VDL7Controller:
    """One pole. Call the input methods as things happen, then `tick` at 1 Hz."""

    def __init__(self, cfg: NodeConfig, flash: Flash, rtc: RtcHoldover, verifier: Verifier,
                 driver: Optional[LuminaireDriver] = None, photocell: Optional[Photocell] = None):
        parse_posix_tz(cfg.tz)                 # a bad rule fails at commissioning, not at dusk
        self.cfg = cfg
        self.flash = flash
        self.rtc = rtc
        self.verifier = verifier
        self.driver = driver or LuminaireDriver.commissioned_for(self.profile, cfg.hin)
        self.photocell = photocell or Photocell()
        self.events = EventStore()
        self.replay = ReplayWindow(hi=flash.replay_hi)
        self.mode = Mode.SAFE
        self.level = 0.0
        self.output: Optional[Output] = None
        self.log: Deque[str] = deque(maxlen=LOG_LINES)
        self.audit: Deque[AuditRecord] = deque(maxlen=LOG_LINES)   # every record also goes to the CMS
        self.failure_level_writes = 0
        self.output_reasons_early = False
        # timers, all node-monotonic
        self._boot_mono: Optional[float] = None
        self._last_backhaul = -math.inf
        self._last_gateway = -math.inf
        self._presence_until = -math.inf
        self._carpet_until = -math.inf
        self._last_checkpoint = -math.inf
        # photocell learning (on clocked nights)
        self._pc_dusk_local: Optional[datetime] = None
        self._seeded = False
        # SAFE-mode anchors
        self._pc_dusk_mono: Optional[float] = None
        self._last_good_dusk_mono: Optional[float] = None
        self._last_raw_dusk_mono: Optional[float] = None    # as observed, weather or not
        self._dark_since: Optional[float] = None
        self._last_dawn_mono: Optional[float] = None        # end of the last full-length night
        self._safe_anchor: Optional[Tuple[float, float]] = None   # (hour, mono)
        # alarms and metering
        self.alarms: Dict[str, float] = {}          # name -> raised at mono
        self._cond_since: Dict[str, float] = {}
        self._tilt_baseline: Optional[float] = flash.checkpoint.tilt_baseline
        self._tilt_last: Optional[float] = None
        cfg.burn_hours = max(cfg.burn_hours, flash.checkpoint.burn_hours)
        self._lit_flips: Deque[float] = deque(maxlen=32)
        self._prev_lit: Optional[bool] = None
        self._meter_slot_start: Optional[float] = None
        self._meter_wh = 0.0

    # ------------------------------------------------------------------ inputs
    @property
    def profile(self) -> ClassProfile:
        return self.flash.bundle.profiles[self.cfg.road]

    def backhaul_hello(self, mono: float, utc: Optional[datetime] = None) -> None:
        """CMS heartbeat over cellular; carries LwM2M time when present.
        One hello returns the node to ONLINE; one time sync leaves SAFE."""
        self._last_backhaul = mono
        if utc is not None:
            self._sync(mono, utc, "backhaul")

    def gnss_fix(self, mono: float, utc: datetime) -> None:
        self._sync(mono, utc, "GNSS")

    def _sync(self, mono: float, utc: datetime, source: str) -> None:
        try:
            self.rtc.sync(mono, utc)
        except ValueError as e:                # keep the clock we have rather than a time we can't place
            self.log.append(f"{mono:.0f} REJECT {source} time sync: {e}")

    def mesh_gateway_seen(self, mono: float) -> None:
        """Mesh layer reports a path to a node with live backhaul."""
        self._last_gateway = mono

    def radar_detect(self, mono: float, cls: str = "pedestrian") -> None:
        self._presence_until = mono + self.flash.bundle.presence_hold_s

    def carpet_event(self, mono: float) -> None:
        """Neighbour detection relayed over the mesh (3 hops, 60 s hold)."""
        self._carpet_until = mono + self.flash.bundle.carpet_hold_s

    def tilt_sample(self, deg: float, mono: float) -> None:
        """Accelerometer tilt from vertical. The first sample after
        commissioning is the baseline; > 2 deg change raises TILT."""
        if self._tilt_baseline is None:
            self.commission_tilt(deg)
        self._tilt_last = deg

    def commission_tilt(self, deg: float) -> None:
        self._tilt_baseline = deg
        self._tilt_last = deg
        self.flash.checkpoint.tilt_baseline = deg

    def photocell_sample(self, lx: float, mono: float) -> None:
        flip = self.photocell.sample(lx, mono)
        if flip is None:
            return
        trusted = self.rtc.trusted(mono)
        utc = self.rtc.utc_now(mono) if trusted else None
        if flip:                               # light -> dark: dusk observed
            self._safe_anchor = None
            self._pc_dusk_local = None
            if utc is not None:                # clocked: learn only from a dusk near the sun's
                self._pc_dusk_mono = mono
                if self._near_sun_transition(utc, dusk=True):
                    self._pc_dusk_local = to_local(utc, self.cfg.tz)
                    self._last_good_dusk_mono = mono
            else:                              # SAFE: reject weather against yesterday's dusk
                self._pc_dusk_mono = self._plausible_dusk(mono)
            self._last_raw_dusk_mono = self._dark_since = mono
        else:                                  # dark -> light: dawn observed
            night_s = self.flash.checkpoint.prev_night_len_h * 3600.0
            if self._dark_since is not None and mono - self._dark_since >= night_s / 2:
                self._last_dawn_mono = mono    # a night, not a passing storm
            self._dark_since = None
            if (utc is not None and self._pc_dusk_local is not None
                    and self._near_sun_transition(utc, dusk=False)):
                self._learn_from_photocell(self._pc_dusk_local, to_local(utc, self.cfg.tz))
            self._pc_dusk_mono = None
            self._safe_anchor = None
            self._pc_dusk_local = None

    def receive(self, msg: SignedMessage, mono: float, via: str = "backhaul") -> bool:
        """Any signed message from the CMS, directly or relayed by the mesh.
        Relays never re-sign, so the same bytes verify everywhere."""
        if not self.verifier.verify(msg.payload, msg.signature):
            self.log.append(f"{mono:.0f} REJECT unsigned/forged message via {via}")
            return False
        if via == "backhaul":
            self._last_backhaul = mono
        try:
            d = msg.decode()
        except ValueError:
            self.log.append(f"{mono:.0f} REJECT undecodable message")
            return False
        if isinstance(d, dict) and d.get("kind") == "bundle":
            return self.flash.install(msg, self.verifier, today=self._today(mono))
        try:
            if not isinstance(d, dict):
                raise TypeError("not an object")
            ev = Event.from_dict(d)
        except (KeyError, ValueError, TypeError) as e:
            self.log.append(f"{mono:.0f} REJECT unknown or malformed event: {e!r}")
            return False
        if not addressed_to(ev.targets, self.cfg.node_id, self.cfg.segment_id):
            return False                                   # not for this pole
        status = self.replay.check(ev.seq)
        if status == "duplicate":
            return False                                   # backhaul + mesh copy
        if status == "stale":
            self.log.append(f"{mono:.0f} REJECT replayed seq {ev.seq} (window top {self.replay.hi})")
            return False
        reason = self._stale_on_arrival(ev, mono)
        if reason:
            self.log.append(f"{mono:.0f} REJECT {ev.kind.value} {ev.id}: {reason}")
            return False
        record = None
        if ev.kind == EventKind.OVERRIDE:
            level = ev.payload.get("level")
            by, why = ev.payload.get("by"), ev.payload.get("reason")
            if (isinstance(level, bool) or not isinstance(level, (int, float)) or not (0 <= level <= 100)
                    or not isinstance(by, str) or not by or not isinstance(why, str) or not why):
                self.log.append(f"{mono:.0f} REJECT override {ev.id}: needs level 0-100, by and reason")
                return False
            utc = self.rtc.utc_now(mono) if self.rtc.trusted(mono) else None
            record = AuditRecord(mono, utc.isoformat() if utc else None, ev.id, float(level),
                                 int(ev.priority), by, why)
        if ev.kind == EventKind.LOOP_VOLUME:
            veh = ev.payload.get("veh15")
            if isinstance(veh, bool) or not isinstance(veh, (int, float)) or veh < 0:
                self.log.append(f"{mono:.0f} REJECT loop volume {ev.id}: bad veh15")
                return False
        # Valid and new: only now consume the sequence number.
        self.replay.accept(ev.seq)
        self.flash.replay_hi = self.replay.hi              # FRAM write in hardware
        ev.via = via
        remaining = self._remaining_ttl(ev, mono)
        ev.age_s, ev.ttl_s = max(0.0, ev.ttl_s - remaining), remaining
        if ev.kind == EventKind.CANCEL:
            target = str(ev.payload.get("target", ""))
            if self.events.cancel(target, mono, ev.seq):
                if any(a.event_id == target for a in self.audit):
                    self._audit(self._audit_last(target), mono, "cancelled")
            else:
                self.log.append(f"{mono:.0f} CANCEL {target} before it arrived: held")
            return True
        if self.events.cancelled_before(ev, mono):
            self.log.append(f"{mono:.0f} REJECT {ev.kind.value} {ev.id}: already cancelled")
            return False
        if record is not None:
            self._audit(record, mono, "applied")
        self.events.put(ev, mono)
        return True

    def pending_uplink(self) -> Optional[dict]:
        """Status, alarms, audit records and buffered metering for the CMS
        (Section 2.1 uplink; Section 5.3 step 6 replay). Records stay in the
        outbox until `ack_uplink`, so a link that dies before the node
        notices loses nothing."""
        if self.mode != Mode.ONLINE:
            return None
        records = list(self.outbox)
        return {"node": self.cfg.node_id, "bundle_version": self.flash.version,
                "alarms": sorted(self.alarms), "records": records,
                "metering": [r for r in records if r["type"] == "meter"],
                "audit": [r for r in records if r["type"] == "audit"],
                "upto": records[-1]["n"] if records else None}

    def ack_uplink(self, upto: Optional[int]) -> None:
        """The CMS confirmed every record up to and including `upto`."""
        while self.outbox and upto is not None and self.outbox[0]["n"] <= upto:
            self.outbox.popleft()

    # ---------------------------------------------------------------- helpers
    def _today(self, mono: float) -> Optional[date]:
        if not self.rtc.trusted(mono):
            return None
        return to_local(self.rtc.utc_now(mono), self.cfg.tz).date()

    def _stale_on_arrival(self, ev: Event, mono: float) -> Optional[str]:
        """With a trusted clock, refuse events that expired before they
        arrived or claim to come from the future."""
        if not self.rtc.trusted(mono) or not ev.issued:
            return None
        try:
            issued = datetime.fromisoformat(ev.issued)
        except ValueError:
            return "bad issued time"
        if issued.tzinfo is None:
            return "issued time without zone"
        now = self.rtc.utc_now(mono)
        age = (now - issued).total_seconds()
        if age > ev.ttl_s + STALE_SKEW_S:
            return f"expired {age - ev.ttl_s:.0f} s before arrival"
        if age < -STALE_SKEW_S:
            return "issued in the future"
        return None

    def _audit_last(self, event_id: str) -> AuditRecord:
        return next(a for a in reversed(self.audit) if a.event_id == event_id)

    def _audit(self, rec: AuditRecord, mono: float, action: str) -> None:
        rec = replace(rec, mono=mono, action=action)
        self.audit.append(rec)
        self._outbox_put({"type": "audit", **rec.__dict__})

    @property
    def outbox(self) -> Deque[dict]:
        return self.flash.outbox

    def _outbox_put(self, record: dict) -> None:
        self.flash.outbox_seq += 1
        record["n"] = self.flash.outbox_seq
        self.flash.outbox.append(record)

    def _remaining_ttl(self, ev: Event, mono: float) -> float:
        """With a trusted clock an event expires at issued + TTL, not at
        receipt + TTL, so a late delivery cannot extend it."""
        if not self.rtc.trusted(mono) or not ev.issued:
            return ev.ttl_s
        try:
            age = (self.rtc.utc_now(mono) - datetime.fromisoformat(ev.issued)).total_seconds()
        except (ValueError, TypeError):
            return ev.ttl_s
        return max(1.0, min(ev.ttl_s, ev.ttl_s - max(0.0, age)))

    def _near_sun_transition(self, utc: datetime, dusk: bool) -> bool:
        """Learn only from photocell transitions within 45 min of the sun's
        own dusk or dawn: storm darkness must not become 'dusk'. The night
        may have begun today or yesterday (a white-night dusk after
        midnight, any dawn), so both are tried; under the midnight sun or in
        polar night there is nothing to learn from."""
        today = to_local(utc, self.cfg.tz).date()
        for d in (today, today - timedelta(days=1)):
            sun_dusk, sun_dawn = night_bounds(self.cfg.lat, self.cfg.lon, d, tz=self.cfg.tz)
            ref = sun_dusk if dusk else sun_dawn
            if ref is not None and abs((utc - ref).total_seconds()) <= LEARN_GATE_S:
                return True
        return False

    def _plausible_dusk(self, mono: float) -> float:
        """SAFE-mode anchor. If a dusk was seen yesterday in this boot, a
        dusk more than 45 min off 24 h later is weather: anchor on the
        expected time instead. The exception is a dusk that agrees with the
        dusk actually seen the evening before, or with the last dawn plus
        the learned length of the day: then the reference itself was weather
        (storm darkness running into the first clockless night, which had
        nothing to be checked against), and this dusk replaces it."""
        last = self._last_good_dusk_mono
        if last is not None:
            expected = last + 86400.0 * round((mono - last) / 86400.0)
            if expected > last and abs(mono - expected) > LEARN_GATE_S:
                off = (mono - expected) / 60
                if self._dusk_confirmed(mono):
                    self.log.append(f"{mono:.0f} SAFE dusk {off:+.0f} min off schedule: confirmed, re-anchoring")
                else:
                    self.log.append(f"{mono:.0f} SAFE dusk {off:+.0f} min off schedule: using expected")
                    self._last_good_dusk_mono = expected
                    return expected
        self._last_good_dusk_mono = mono
        return mono

    def _dusk_confirmed(self, mono: float) -> bool:
        """Does a second, independent observation put dusk here?"""
        def near(ref: Optional[float], min_days: int) -> bool:
            if ref is None:
                return False
            days = round((mono - ref) / 86400.0)
            return days >= min_days and abs(mono - ref - 86400.0 * days) <= LEARN_GATE_S
        day_s = 86400.0 - self.flash.checkpoint.prev_night_len_h * 3600.0
        dawn = self._last_dawn_mono
        return near(self._last_raw_dusk_mono, 1) or near(dawn + day_s if dawn is not None else None, 0)

    def _seed_learning(self, utc: datetime) -> None:
        """First trusted tick: seed tonight's dark midpoint from the astro
        clock so SAFE mode has a value before a photocell night is learned."""
        cp = self.flash.checkpoint
        if cp.learned:
            return
        loc = to_local(utc, self.cfg.tz)
        d = loc.date() if loc.hour >= 12 else (loc - timedelta(days=1)).date()
        night = learned_night(self.cfg.lat, self.cfg.lon, d, tz=self.cfg.tz)
        if night is not None:                  # none under the midnight sun or in polar night
            cp.learned_midpoint_h, cp.prev_night_len_h = night

    def _learn_from_photocell(self, dusk: datetime, dawn: datetime) -> None:
        """Re-learn the midpoint and length of the night *as the photocell
        sees it*, so SAFE mode counts from the same kind of dusk it learned
        from. Storm darkness (too short) and odd nights are ignored."""
        length = (dawn - dusk).total_seconds() / 3600.0
        if not (6.0 <= length <= 18.0):
            return
        dusk_h = dusk.hour + dusk.minute / 60.0 + dusk.second / 3600.0
        cp = self.flash.checkpoint
        cp.learned_midpoint_h = (dusk_h + length / 2.0) % 24.0
        cp.prev_night_len_h = length
        cp.learned = True

    def _safe_night_hour(self, mono: float) -> Optional[float]:
        """Night-hour estimate with no wall clock (Section 5.3 step 5):
        learned midpoint + (time since dusk - previous night length / 2).
        Anchored on a photocell dusk seen this boot, or on the flash
        checkpoint when the RTC counter can measure the gap since it."""
        cp = self.flash.checkpoint
        if self._pc_dusk_mono is not None:
            dusk_hour = (cp.learned_midpoint_h - cp.prev_night_len_h / 2.0) % 24.0
            return (dusk_hour + (mono - self._pc_dusk_mono) / 3600.0) % 24.0
        if (self._safe_anchor is None and self.photocell.dark and cp.lit and cp.night_hour is not None
                and cp.rtc_epoch == self.rtc.epoch):
            gap = self.rtc.raw(mono) - cp.rtc_raw
            if 0.0 <= gap <= 12 * 3600.0:
                self._safe_anchor = ((cp.night_hour + gap / 3600.0) % 24.0, mono)
        if self._safe_anchor is not None:
            h0, m0 = self._safe_anchor
            return (h0 + (mono - m0) / 3600.0) % 24.0
        return None

    def _write_checkpoint(self, mono: float, hour: Optional[float], lit: bool) -> None:
        cp = self.flash.checkpoint
        cp.night_hour, cp.lit = hour, lit
        cp.rtc_epoch, cp.rtc_raw = self.rtc.epoch, self.rtc.raw(mono)
        cp.bundle_version = self.flash.version
        cp.burn_hours = self.cfg.burn_hours
        cp.tilt_baseline = self._tilt_baseline
        self._last_checkpoint = mono

    def _hold(self, name: str, cond: bool, mono: float, after_s: float) -> None:
        """Raise alarm `name` once `cond` has held for `after_s`; clear it when
        the condition goes away."""
        if cond:
            since = self._cond_since.setdefault(name, mono)
            if mono - since >= after_s and name not in self.alarms:
                self.alarms[name] = mono
                self.log.append(f"{mono:.0f} ALARM {name}")
        else:
            self._cond_since.pop(name, None)
            if name in self.alarms:
                del self.alarms[name]
                self.log.append(f"{mono:.0f} CLEAR {name}")

    def _alarms_and_metering(self, mono: float, dt: float, lit: bool, relay_on: bool, drive: float,
                             expired: bool) -> None:
        design_w = self.profile.design_watts
        measured = self.driver.measured_w(design_w)
        # tilt: > 2 deg from the commissioning baseline
        tilt = (self._tilt_baseline is not None and self._tilt_last is not None
                and abs(self._tilt_last - self._tilt_baseline) > TILT_ALARM_DEG)
        self._hold("TILT", tilt, mono, 0.0)
        # driver fault: commanded on, drawing standby only
        self._hold("DRIVER_FAULT", relay_on and drive > 10.0 and measured < STANDBY_W + 0.05 * design_w, mono, 60.0)
        # day-burner: commanded off, still drawing real power
        self._hold("DAY_BURNER", (not relay_on) and measured > 0.10 * design_w, mono, 300.0)
        # cycling: more than 6 lit/unlit transitions in an hour
        if self._prev_lit is not None and lit != self._prev_lit:
            self._lit_flips.append(mono)
        self._prev_lit = lit
        flips = sum(1 for m in self._lit_flips if mono - m <= 3600.0)
        self._hold("CYCLING", flips > 6, mono, 0.0)
        self._hold("BUNDLE_EXPIRED", expired, mono, 0.0)
        # photocell stuck dark: lit by the photocell alone in daylight for hours
        early = bool(self.output_reasons_early)
        self._hold("PHOTOCELL_FAULT", early, mono, PHOTOCELL_FAULT_S)
        # 15-min metering into the outbox (sent when ONLINE, buffered otherwise)
        if self._meter_slot_start is None:
            self._meter_slot_start = mono
        self._meter_wh += measured * dt / 3600.0
        if mono + dt - self._meter_slot_start >= METER_SLOT_S:
            utc = self.rtc.utc_now(mono) if self.rtc.trusted(mono) else None
            self._outbox_put({"type": "meter", "slot_end_mono": round(mono + dt, 1),
                              "slot_end_utc": utc.isoformat() if utc else None,
                              "wh": round(self._meter_wh, 3), "mode": self.mode.value})
            self._meter_slot_start = mono + dt
            self._meter_wh = 0.0

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
            hour: Optional[float] = local_hour(utc, cfg.tz)
            elevation = solar_elevation_deg(cfg.lat, cfg.lon, utc)
            astro_night = elevation < cfg.night_elevation_deg
            lit = astro_night or pc_dark
            self.output_reasons_early = pc_dark and not astro_night
            storm_dark = pc_dark and elevation >= 0.0          # dark with the sun up: storm darkness (R-SAF-4)
            if pc_dark and not astro_night:
                reasons.append("PHOTOCELL_EARLY")
            if astro_night and not pc_dark:
                reasons.append("PHOTOCELL_VETOED")
        else:
            self.output_reasons_early = False
            storm_dark = False
            lit = pc_dark
            hour = self._safe_night_hour(mono) if lit else None
            reasons.append("SAFE_CLOCK" if hour is not None else "SAFE_NO_ANCHOR")

        # 3. Phase -> base level (no estimate: hold the 22:00 level). A zone
        #    overlay replaces the class levels; on a migration night the
        #    presence classes hold their 22:00 level from dusk. Storm darkness
        #    with the sun up (R-SAF-4) keeps the evening level whatever the alert.
        if storm_dark:
            phase = Phase.EVENING
        else:
            phase = phase_for_hour(hour) if hour is not None else Phase.STEP
        levels = bundle.levels_for(cfg.road, cfg.zone)
        if cfg.zone and cfg.road in bundle.zones.get(cfg.zone, {}):
            reasons.append(f"ZONE:{cfg.zone}")
        base = levels[PHASE_ORDER.index(phase)]
        if (self.events.latest(EventKind.MIGRATION, mono) is not None and cfg.road in bundle.migration_classes
                and not storm_dark):
            step_level = levels[PHASE_ORDER.index(Phase.STEP)]
            if base > step_level:
                base = step_level
            reasons.append("MIGRATION")

        # 4. Activity in [0, 1]. Loop volume only while ONLINE or relayed in MESH,
        #    and only while its event is live and the count is under
        #    loop_max_age_s old, counted from issue rather than arrival.
        activity = 0.0
        loop = self.events.latest(EventKind.LOOP_VOLUME, mono) if mode in LOOP_MODES else None
        if (loop is not None and prof.design_volume
                and (mono - loop.received_mono + loop.age_s) <= cfg.loop_max_age_s):
            activity = min(1.0, max(0.0, float(loop.payload["veh15"]) / prof.design_volume))
            if activity > 0:
                reasons.append("LOOP")
        presence = mono < self._presence_until
        carpet = mono < self._carpet_until
        if presence or carpet:
            activity = max(activity, 1.0 if prof.occupancy else 0.5)
            reasons.append("PRESENCE" if presence else "CARPET")

        # 5. Raise toward the boost cap, never below the base level
        target = float(base)
        if activity > 0:
            target = max(target, target + (prof.boost_cap - target) * activity)

        # 6. Weather: rain +15 up to the cap (never lowers); fog and snow logged
        if self.events.latest(EventKind.RAIN, mono) is not None:
            target = max(target, min(float(prof.boost_cap), target + bundle.rain_boost))
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
        emergency = self.events.latest(EventKind.EMERGENCY, mono)
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

        # 12. Output, DALI failure level, checkpoint, alarms, metering, hour meter
        relay_on = lit or self.level > 0.5          # let the dawn fade finish
        want_fail = failure_level(prof, cfg.hin, bundle.hin_floor)
        if self.driver.system_failure_level != want_fail:     # DALI NVM write only on change
            self.driver.system_failure_level = want_fail
            self.failure_level_writes += 1
        self.driver.set(white, amber, relay_on, mono)
        if mono - self._last_checkpoint >= cfg.checkpoint_interval_s:
            self._write_checkpoint(mono, hour, lit)
        expired = utc is not None and bundle.version > 0 and bundle_expired(bundle, to_local(utc, cfg.tz).date())
        if expired:
            reasons.append("BUNDLE_EXPIRED")
        self._alarms_and_metering(mono, dt, lit, relay_on, drive, expired)
        if lit:
            cfg.burn_hours += dt / 3600.0
        reasons.insert(0, f"MODE_{mode.value}")
        reasons.insert(1, f"PHASE_{phase.value.upper()}")
        self.output = Output(mono, mode, lit, phase, hour, base, activity, target, self.level,
                             drive, white, amber, reasons, tuple(sorted(self.alarms)))
        return self.output

    # ------------------------------------------------------------------ power
    def reboot(self) -> "VDL7Controller":
        """A new controller on what survives in flash, the RTC and the driver.
        RAM state (events, timers, slew level, audit buffer) is gone; the
        flash image is re-verified as at power-up."""
        flash = Flash.boot(self.flash.image(), self.verifier)
        return VDL7Controller(self.cfg, flash, self.rtc, self.verifier, self.driver,
                              Photocell(self.photocell.on_lx, self.photocell.off_lx, self.photocell.debounce_s))
