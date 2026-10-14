"""Night-time demand: traffic on the loops and people on the sidewalks.

These are the ASSUMED curves of Section 6.4, shared by the network
simulation (which draws seeded pedestrians and noisy loop counts from them)
and the annual business case (which uses their expected values). Replace
them with DDOT's ATSPM counts and a pedestrian count programme before
quoting numbers for a specific corridor.
"""
from __future__ import annotations

from typing import List, Tuple

from .profiles import RoadClass

# (hour, value) with hours after midnight written as 24+
TRAFFIC: List[Tuple[float, float]] = [(18, 290), (20, 210), (22, 130), (24, 60), (27, 25), (29, 60), (31, 250), (32, 290)]
PEDS: List[Tuple[float, float]] = [(18, 30), (21, 15), (23, 6), (25, 2), (27, 1), (29, 2), (31, 15), (32, 20)]
COLLECTOR_TRAFFIC_SHARE = 0.42      # collector volume relative to the arterial curve

# Section 6.3 street model: walkers enter at either end of a 20-pole street
# and walk 4-14 poles at 1.4 m/s past poles 30 m apart.
POLES = 20
POLE_SPACING_M = 30.0
WALK_SPEED_MPS = 1.4
WALK_POLES = (4, 14)


def _pw(points: List[Tuple[float, float]], h: float) -> float:
    """Piecewise-linear curve over a 24 h clock given as (hour, value) with
    hours after midnight written as 24+."""
    hh = h if h >= 12 else h + 24
    for (h0, v0), (h1, v1) in zip(points, points[1:]):
        if h0 <= hh <= h1:
            return v0 + (v1 - v0) * (hh - h0) / (h1 - h0)
    return points[-1][1] if hh > points[-1][0] else points[0][1]


def traffic_veh15(h: float, road: RoadClass) -> float:
    """Expected vehicles per 15 min on the segment's loop at local hour h."""
    base = _pw(TRAFFIC, h)
    return base if road == RoadClass.ARTERIAL else base * COLLECTOR_TRAFFIC_SHARE


def ped_rate_per_h(h: float) -> float:
    """Pedestrians entering a 20-pole street per hour at local hour h."""
    return _pw(PEDS, h)
