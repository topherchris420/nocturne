"""Road-class dimming profiles, phases, floors and the signed profile bundle.

Section 2.2 of the spec. Levels are percent of commissioned design output,
where 100 % meets the RP-8 maintained target for the segment's peak
pedestrian-conflict class. Floors for arterials, collectors and local streets
stay at or above the lowest applicable RP-8 class; alleys and park edges
carry policy minimums.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple


def _int(x, name: str) -> int:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != int(x):
        raise TypeError(f"{name} must be an integer, got {x!r}")
    return int(x)


def _num(x, name: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError(f"{name} must be a number, got {x!r}")
    return float(x)


def _bool(x, name: str) -> bool:
    if not isinstance(x, bool):
        raise TypeError(f"{name} must be true or false, got {x!r}")
    return x


def _str(x, name: str) -> str:
    if not isinstance(x, str):
        raise TypeError(f"{name} must be a string, got {x!r}")
    return x


class RoadClass(str, Enum):
    ARTERIAL = "arterial"
    COLLECTOR = "collector"
    LOCAL = "local"
    ALLEY = "alley"
    PARK = "park"


class Phase(str, Enum):
    EVENING = "evening"   # dusk-22:00
    STEP = "step"         # 22:00-23:00
    CURFEW = "curfew"     # 23:00-01:00
    DEEP = "deep"         # 01:00-05:00
    DAWN = "dawn"         # 05:00-dawn


PHASE_ORDER = (Phase.EVENING, Phase.STEP, Phase.CURFEW, Phase.DEEP, Phase.DAWN)


def phase_for_hour(h: float) -> Phase:
    """Local civil hour (0-24, fractional) to dimming phase. Boundaries are
    local time, so the curfew follows DST. Hours outside the night map to the
    evening phase so storm darkness at 14:00 lights at the evening level."""
    h = h % 24.0
    if 22.0 <= h < 23.0:
        return Phase.STEP
    if h >= 23.0 or h < 1.0:
        return Phase.CURFEW
    if 1.0 <= h < 5.0:
        return Phase.DEEP
    if 5.0 <= h < 12.0:
        return Phase.DAWN
    return Phase.EVENING


@dataclass(frozen=True)
class ClassProfile:
    road: RoadClass
    levels: Tuple[int, int, int, int, int]   # evening, step, curfew, deep, dawn
    floor: int
    boost_cap: int
    design_volume: Optional[int]             # veh / 15 min that counts as full
    occupancy: bool                          # presence sets activity = 1
    design_watts: float                      # today's 3000K-equivalent fixture
    cct_today: int
    cct_target: str

    def base(self, phase: Phase) -> int:
        return self.levels[PHASE_ORDER.index(phase)]

    @property
    def rp8_class(self) -> bool:
        """Whether the floor is an RP-8 class (True) or a policy minimum."""
        return self.road in (RoadClass.ARTERIAL, RoadClass.COLLECTOR, RoadClass.LOCAL)

    def to_dict(self) -> dict:
        return {
            "road": self.road.value, "levels": list(self.levels), "floor": self.floor,
            "boost_cap": self.boost_cap, "design_volume": self.design_volume,
            "occupancy": self.occupancy, "design_watts": self.design_watts,
            "cct_today": self.cct_today, "cct_target": self.cct_target,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ClassProfile":
        """Strict: a signed bundle with a wrong type is refused, not coerced."""
        levels = d["levels"]
        if not isinstance(levels, list) or len(levels) != len(PHASE_ORDER):
            raise TypeError("levels must be a list of five numbers")
        vol = d["design_volume"]
        return cls(RoadClass(d["road"]), tuple(_int(x, "level") for x in levels), _int(d["floor"], "floor"),
                   _int(d["boost_cap"], "boost_cap"), None if vol is None else _int(vol, "design_volume"),
                   _bool(d["occupancy"], "occupancy"), _num(d["design_watts"], "design_watts"),
                   _int(d["cct_today"], "cct_today"), _str(d["cct_target"], "cct_target"))


# Section 2.2 table
DEFAULT_PROFILES: Dict[RoadClass, ClassProfile] = {
    RoadClass.ARTERIAL: ClassProfile(RoadClass.ARTERIAL, (100, 80, 60, 50, 75), 50, 100, 300, False, 120.0, 3000, "2700K"),
    RoadClass.COLLECTOR: ClassProfile(RoadClass.COLLECTOR, (100, 70, 50, 40, 65), 40, 90, 120, False, 80.0, 3000, "2200K"),
    RoadClass.LOCAL: ClassProfile(RoadClass.LOCAL, (80, 60, 40, 30, 50), 30, 70, None, True, 40.0, 2700, "2200K"),
    RoadClass.ALLEY: ClassProfile(RoadClass.ALLEY, (70, 50, 30, 20, 40), 20, 70, None, True, 30.0, 2700, "2200K"),
    RoadClass.PARK: ClassProfile(RoadClass.PARK, (60, 40, 20, 10, 30), 10, 50, None, True, 30.0, 2700, "PC-Amber"),
}

# Section 4.3 tunable-white mix (white : amber) by phase
DEFAULT_MIX: Dict[Phase, Tuple[int, int]] = {
    Phase.EVENING: (100, 0),
    Phase.STEP: (60, 40),
    Phase.CURFEW: (0, 100),
    Phase.DEEP: (0, 100),
    Phase.DAWN: (60, 40),
}
BOOST_MIX: Tuple[int, int] = (100, 0)   # presence or emergency: full colour rendering

HIN_FLOOR = 60        # Vision Zero High-Injury Network floor, every class
# Migration nights (EventKind.MIGRATION): these classes hold their 22:00 level
# from dusk. They are the classes with radar presence, so anyone walking still
# gets the full boost; arterials and collectors keep their traffic-led levels.
MIGRATION_CLASSES: Tuple[RoadClass, ...] = (RoadClass.LOCAL, RoadClass.ALLEY, RoadClass.PARK)
MAX_ZONES = 32        # fixed-size table on the MCU
RAIN_BOOST = 15       # points, capped at the boost cap
PRESENCE_HOLD_S = 90
CARPET_HOLD_S = 60
CARPET_HOPS = 3


def clo_factor(burn_hours: float, new: float = 0.86, end_of_life_h: float = 100_000.0) -> float:
    """Constant light output: drive rises from 0.86 when new to 1.00 at
    100,000 h so delivered lumens stay flat as the LEDs depreciate."""
    f = max(0.0, min(1.0, burn_hours / end_of_life_h))
    return new + (1.0 - new) * f


@dataclass
class ProfileBundle:
    """What the CMS signs and the node stores in two flash banks."""
    version: int
    issued: str                                  # ISO date, informational only
    valid_days: int = 400
    profiles: Dict[RoadClass, ClassProfile] = field(default_factory=lambda: dict(DEFAULT_PROFILES))
    mix: Dict[Phase, Tuple[int, int]] = field(default_factory=lambda: dict(DEFAULT_MIX))
    hin_floor: int = HIN_FLOOR
    rain_boost: int = RAIN_BOOST
    presence_hold_s: float = PRESENCE_HOLD_S
    carpet_hold_s: float = CARPET_HOLD_S
    # Neighbourhood overlays: zone name -> road class -> five phase levels.
    # A node commissioned into a zone (NodeConfig.zone) runs these instead of
    # its class levels: darker around dark-sky parks and river corridors,
    # brighter for longer on a nightlife strip. Floors, boosts and caps are
    # still the class's; the levels are validated against the same floors.
    zones: Dict[str, Dict[RoadClass, Tuple[int, int, int, int, int]]] = field(default_factory=dict)
    migration_classes: Tuple[RoadClass, ...] = MIGRATION_CLASSES

    def levels_for(self, road: RoadClass, zone: Optional[str]) -> Tuple[int, int, int, int, int]:
        z = self.zones.get(zone) if zone else None
        if z is not None and road in z:
            return z[road]
        return self.profiles[road].levels

    def to_dict(self) -> dict:
        return {
            "kind": "bundle",
            "version": self.version,
            "issued": self.issued,
            "valid_days": self.valid_days,
            "profiles": {k.value: v.to_dict() for k, v in self.profiles.items()},
            "mix": {k.value: list(v) for k, v in self.mix.items()},
            "hin_floor": self.hin_floor,
            "rain_boost": self.rain_boost,
            "presence_hold_s": self.presence_hold_s,
            "carpet_hold_s": self.carpet_hold_s,
            "zones": {name: {r.value: list(lv) for r, lv in z.items()} for name, z in self.zones.items()},
            "migration_classes": [r.value for r in self.migration_classes],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProfileBundle":
        """Raises KeyError/ValueError/TypeError on a malformed bundle."""
        if not isinstance(d.get("profiles"), dict) or not isinstance(d.get("mix"), dict):
            raise TypeError("profiles and mix must be objects")
        mix = {}
        for k, v in d["mix"].items():
            if not isinstance(v, list) or len(v) != 2:
                raise TypeError(f"mix {k} must be [white, amber]")
            mix[Phase(k)] = (_int(v[0], "mix"), _int(v[1], "mix"))
        zones_raw = d.get("zones", {})
        if not isinstance(zones_raw, dict):
            raise TypeError("zones must be an object")
        zones: Dict[str, Dict[RoadClass, Tuple[int, int, int, int, int]]] = {}
        for name, z in zones_raw.items():
            if not isinstance(z, dict):
                raise TypeError(f"zone {name} must be an object")
            zones[_str(name, "zone name")] = {}
            for road, lv in z.items():
                if not isinstance(lv, list) or len(lv) != len(PHASE_ORDER):
                    raise TypeError(f"zone {name} {road} levels must be a list of five numbers")
                zones[name][RoadClass(road)] = tuple(_int(x, "zone level") for x in lv)   # type: ignore[assignment]
        mig = d.get("migration_classes", [r.value for r in MIGRATION_CLASSES])
        if not isinstance(mig, list):
            raise TypeError("migration_classes must be a list")
        return cls(
            version=_int(d["version"], "version"), issued=_str(d["issued"], "issued"),
            valid_days=_int(d.get("valid_days", 400), "valid_days"),
            profiles={RoadClass(k): ClassProfile.from_dict(v) for k, v in d["profiles"].items()},
            mix=mix,
            hin_floor=_int(d.get("hin_floor", HIN_FLOOR), "hin_floor"),
            rain_boost=_int(d.get("rain_boost", RAIN_BOOST), "rain_boost"),
            presence_hold_s=_num(d.get("presence_hold_s", PRESENCE_HOLD_S), "presence_hold_s"),
            carpet_hold_s=_num(d.get("carpet_hold_s", CARPET_HOLD_S), "carpet_hold_s"),
            zones=zones,
            migration_classes=tuple(RoadClass(_str(r, "migration class")) for r in mig),
        )


def default_bundle(version: int = 1, issued: str = "2026-10-13") -> ProfileBundle:
    return ProfileBundle(version=version, issued=issued)


# ----------------------------------------------------------------- guards
# Compiled into firmware. A signed bundle may raise these, never lower them:
# a bad or compromised bundle cannot take a street below its RP-8 class or
# policy minimum, or a High-Injury Network segment below 60 %.
FIRMWARE_MIN_FLOOR: Dict[RoadClass, int] = {r: p.floor for r, p in DEFAULT_PROFILES.items()}
FIRMWARE_MIN_HIN = 60
MAX_RAIN_BOOST = 30
MAX_HOLD_S = 600.0


def validate_bundle(b: ProfileBundle) -> List[str]:
    """Every reason the node would refuse this bundle; empty means valid."""
    errs: List[str] = []
    for road in RoadClass:
        p = b.profiles.get(road)
        if p is None:
            errs.append(f"{road.value}: missing")
            continue
        if p.road != road:
            errs.append(f"{road.value}: profile labelled {p.road.value}")
        if len(p.levels) != len(PHASE_ORDER):
            errs.append(f"{road.value}: {len(p.levels)} levels, need {len(PHASE_ORDER)}")
            continue
        if p.floor < FIRMWARE_MIN_FLOOR[road]:
            errs.append(f"{road.value}: floor {p.floor} below firmware minimum {FIRMWARE_MIN_FLOOR[road]}")
        if not (p.floor <= p.boost_cap <= 100):
            errs.append(f"{road.value}: boost cap {p.boost_cap} outside [floor, 100]")
        for ph, lv in zip(PHASE_ORDER, p.levels):
            if not (p.floor <= lv <= 100):
                errs.append(f"{road.value}: {ph.value} level {lv} outside [floor {p.floor}, 100]")
        if p.design_volume is not None and p.design_volume <= 0:
            errs.append(f"{road.value}: design volume must be positive")
    for ph in PHASE_ORDER:
        mix = b.mix.get(ph)
        if mix is None or len(mix) != 2 or min(mix) < 0 or sum(mix) != 100:
            errs.append(f"mix {ph.value}: {mix} must be two non-negative parts summing to 100")
    if b.hin_floor < FIRMWARE_MIN_HIN:
        errs.append(f"hin_floor {b.hin_floor} below {FIRMWARE_MIN_HIN}")
    if not (0 <= b.rain_boost <= MAX_RAIN_BOOST):
        errs.append(f"rain_boost {b.rain_boost} outside [0, {MAX_RAIN_BOOST}]")
    for name in ("presence_hold_s", "carpet_hold_s"):
        v = getattr(b, name)
        if not (0 < v <= MAX_HOLD_S):
            errs.append(f"{name} {v} outside (0, {MAX_HOLD_S}]")
    if len(b.zones) > MAX_ZONES:
        errs.append(f"{len(b.zones)} zones, firmware holds {MAX_ZONES}")
    for name, z in b.zones.items():
        if not (1 <= len(name) <= 32):
            errs.append(f"zone name {name!r} must be 1-32 characters")
        for road, lv in z.items():
            p = b.profiles.get(road)
            lo = max(FIRMWARE_MIN_FLOOR[road], p.floor if p else 0)
            if len(lv) != len(PHASE_ORDER):
                errs.append(f"zone {name} {road.value}: {len(lv)} levels, need {len(PHASE_ORDER)}")
                continue
            for ph, v in zip(PHASE_ORDER, lv):
                if v < lo:
                    errs.append(f"zone {name} {road.value}: {ph.value} level {v} below floor {lo}")
                elif v > 100:
                    errs.append(f"zone {name} {road.value}: {ph.value} level {v} above 100")
    if len(set(b.migration_classes)) != len(b.migration_classes):
        errs.append("migration_classes repeats a class")
    if not (1 <= b.valid_days <= 400):
        errs.append(f"valid_days {b.valid_days} outside [1, 400]")
    try:
        date.fromisoformat(b.issued)
    except ValueError:
        errs.append(f"issued {b.issued!r} is not an ISO date")
    return errs


def bundle_expired(b: ProfileBundle, today: date) -> bool:
    return today > date.fromisoformat(b.issued) + timedelta(days=b.valid_days)
