"""Phase 0: the schedules a central management system can load today.

DC's lights already sit on networked nodes that can run a stored dimming
programme. Phase 0 needs nothing more than a programme per road class,
switching at dusk and dawn on the node's astronomical clock and at fixed
local times in between. This module writes those programmes in a
vendor-neutral JSON the integrator maps onto the CMS's own format (TALQ
control programs, or the vendor's profile import), plus the wave-by-wave
assignment of street segments from the pilot plan.

The levels are the signed bundle's, with two rules for running without
sensors or live data:

* streets that would rely on radar presence (local, alley, park) never go
  below `unsensed_floor`, because nothing brings them back up when someone
  walks in;
* arterials and collectors step hourly through the night at the highest
  level their expected loop volume would ask for in that hour (Section
  6.4 traffic curve), because no live volume arrives to raise them.

Segments on the Vision Zero High-Injury Network get their own programmes
(`hin/<class>`, and `<zone>/hin/<class>` for zone overlays) that never go
below the bundle's HIN floor, as the firmware would hold them. The
inventory does not say which segments those are, so the integrator assigns
these programmes from the city's HIN list.

The business case (vdl7.annual) integrates exactly these programmes, so the
Phase 0 saving it reports is the saving of the files written here.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .demand import traffic_veh15
from .profiles import PHASE_ORDER, ClassProfile, Phase, ProfileBundle, RoadClass, default_bundle, phase_for_hour

SCHEMA = "nocturne-phase0-program/1"
UNSENSED_FLOOR = 50.0
PHASE_START = {Phase.STEP: 22, Phase.CURFEW: 23, Phase.DEEP: 1, Phase.DAWN: 5}
NIGHT_HOURS = [22, 23] + list(range(12))            # hourly steps for traffic classes, to the latest dawns (Paris 08:28, Tromso 11:30)


def check_floor(unsensed_floor: float) -> float:
    """The unsensed floor is a share of full output: finite, 0-100 %."""
    if not (isinstance(unsensed_floor, (int, float)) and math.isfinite(unsensed_floor)
            and 0.0 <= unsensed_floor <= 100.0):
        raise ValueError(f"unsensed floor {unsensed_floor!r} must be a percentage from 0 to 100")
    return float(unsensed_floor)


@dataclass(frozen=True)
class Step:
    at: str                   # "dusk", "dawn" or local "HH:MM"
    level: int                # % of commissioned full output (0 at dawn)


def _traffic_level(prof: ClassProfile, base: float, h0: float, h1: float) -> float:
    """Highest level the expected loop volume asks for in local hours
    [h0, h1), sampled every 5 minutes."""
    best = base
    n = max(1, int(round((h1 - h0) * 12)))
    for i in range(n + 1):
        h = (h0 + (h1 - h0) * i / n) % 24.0
        a = min(1.0, traffic_veh15(h, prof.road) / prof.design_volume)
        best = max(best, base + (prof.boost_cap - base) * a)
    return best


def program(prof: ClassProfile, unsensed_floor: float = UNSENSED_FLOOR,
            levels: Optional[Tuple[int, ...]] = None, hin_floor: Optional[float] = None) -> List[Step]:
    """The night's steps for one road class (or a zone's levels for it); with
    `hin_floor`, for a segment on the High-Injury Network."""
    check_floor(unsensed_floor)
    lv = levels or prof.levels
    base = {ph: float(v) for ph, v in zip(PHASE_ORDER, lv)}
    if prof.design_volume:
        steps = [Step("dusk", math.ceil(_traffic_level(prof, base[Phase.EVENING], 18.0, 22.0)))]
        for h in NIGHT_HOURS:
            b = base[phase_for_hour(h + 0.5)]
            steps.append(Step(f"{h:02d}:00", math.ceil(_traffic_level(prof, b, h, h + 1.0))))
    else:
        floor = max(float(prof.floor), unsensed_floor)
        steps = [Step("dusk", math.ceil(max(base[Phase.EVENING], floor)))]
        for ph, h in PHASE_START.items():
            steps.append(Step(f"{h:02d}:00", math.ceil(max(base[ph], floor))))
    if hin_floor is not None:
        steps = [Step(s.at, max(s.level, math.ceil(hin_floor))) for s in steps]
    steps = [s for i, s in enumerate(steps) if i == 0 or s.level != steps[i - 1].level]   # drop no-op steps
    steps.append(Step("dawn", 0))
    return steps


def level_at(steps: Sequence[Step], local_hour: float) -> float:
    """The programme's level at a local hour during the night (dusk and
    dawn themselves are the lit window, handled by the caller)."""
    def key(s: Step) -> float:
        hh = int(s.at[:2]) + int(s.at[3:]) / 60.0
        return hh + 24.0 if hh < 12.0 else hh
    h = local_hour + 24.0 if local_hour < 12.0 else local_hour
    current = steps[0].level
    for s in steps[1:-1]:
        if key(s) <= h:
            current = s.level
    return float(current)


def programs(bundle: Optional[ProfileBundle] = None, unsensed_floor: float = UNSENSED_FLOOR) -> Dict[str, dict]:
    """One programme per road class, plus one per zone overlay and class,
    each with a High-Injury Network variant wherever the HIN floor changes it."""
    bundle = bundle or default_bundle()
    out: Dict[str, dict] = {}

    def add(name: str, road: RoadClass, levels: Optional[Tuple[int, ...]], **extra) -> None:
        prof = bundle.profiles[road]
        steps = program(prof, unsensed_floor, levels)
        out[name] = {"road_class": road.value, **extra, "steps": [s.__dict__ for s in steps]}
        hin = program(prof, unsensed_floor, levels, hin_floor=bundle.hin_floor)
        if hin != steps:
            prefix, _, cls = name.rpartition("/")
            out[f"{prefix + '/' if prefix else ''}hin/{cls}"] = {"road_class": road.value, **extra, "hin": True,
                                                                  "steps": [s.__dict__ for s in hin]}

    for road in RoadClass:
        add(road.value, road, None)
    for zone, z in bundle.zones.items():
        for road, lv in z.items():
            add(f"{zone}/{road.value}", road, lv, zone=zone)
    return out


def export(bundle: Optional[ProfileBundle] = None, tz: str = "", unsensed_floor: float = UNSENSED_FLOOR) -> str:
    bundle = bundle or default_bundle()
    doc = {
        "schema": SCHEMA, "bundle_version": bundle.version, "tz": tz,
        "dusk_dawn": "sun 3 degrees below the horizon on the node's astronomical clock; "
                     "the node's photocell may switch on earlier, never hold the light off",
        "level": "percent of each luminaire's commissioned full output",
        "unsensed_floor_pct": unsensed_floor,
        "hin_floor_pct": bundle.hin_floor,
        "hin": "programmes marked hin are for segments on the High-Injury Network; assign them from the city's list",
        "programs": programs(bundle, unsensed_floor),
    }
    return json.dumps(doc, indent=2) + "\n"
