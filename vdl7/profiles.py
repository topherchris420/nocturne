"""Road-class dimming profiles, phases, floors and the signed profile bundle.

Section 2.2 of the spec. Levels are percent of commissioned design output,
where 100 % meets the RP-8 maintained target for the segment's peak
pedestrian-conflict class. Floors for arterials, collectors and local streets
stay at or above the lowest applicable RP-8 class; alleys and park edges
carry policy minimums.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple


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
        return cls(RoadClass(d["road"]), tuple(d["levels"]), d["floor"], d["boost_cap"],
                   d["design_volume"], d["occupancy"], d["design_watts"],
                   d["cct_today"], d["cct_target"])


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
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProfileBundle":
        return cls(
            version=int(d["version"]), issued=d["issued"], valid_days=int(d.get("valid_days", 400)),
            profiles={RoadClass(k): ClassProfile.from_dict(v) for k, v in d["profiles"].items()},
            mix={Phase(k): tuple(v) for k, v in d["mix"].items()},
            hin_floor=int(d.get("hin_floor", HIN_FLOOR)), rain_boost=int(d.get("rain_boost", RAIN_BOOST)),
            presence_hold_s=float(d.get("presence_hold_s", PRESENCE_HOLD_S)),
            carpet_hold_s=float(d.get("carpet_hold_s", CARPET_HOLD_S)),
        )


def default_bundle(version: int = 1, issued: str = "2026-10-13") -> ProfileBundle:
    return ProfileBundle(version=version, issued=issued)
