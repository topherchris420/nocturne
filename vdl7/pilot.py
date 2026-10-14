"""Roll out like a trial: a randomised, auditable pilot with a safety brake.

Dimming streets is a public-safety decision, so the rollout is designed to
produce evidence as it goes, the way Steinbach et al. (2015, J Epidemiol
Community Health 69:1118) studied part-night lighting across 62 English
authorities and Chalfin et al. (2022, J Quant Criminol 38:127) randomised
lighting in New York public housing:

* **Stepped wedge.** Street segments are stratified by ward and road class
  and randomised into waves; each wave switches on a scheduled date, so
  every segment is a control until its turn and every ward moves together.
* **Auditable randomisation.** The seed is the SHA-256 of a public string
  fixed before the draw (a dated lottery result, a council resolution
  number), so anyone can re-run the assignment and get the same plan.
* **Safety brake.** At each scheduled look, night-time crashes (or any
  harm count) on switched segments are compared with not-yet-switched
  segments over the same nights by an exact conditional test, with the
  error rate split across looks. A signal pauses the next wave and reverts
  the affected class's bundle; it never waits for the end of the pilot.
* **Power.** `exposure_needed` says how many segment-nights a given
  baseline rate needs to detect a given change, before anyone commits.
"""
from __future__ import annotations

import csv
import hashlib
import math
import os
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import NormalDist
from typing import Dict, List, Optional, Sequence, Tuple

SEGMENTS_DC = os.path.join(os.path.dirname(__file__), "..", "data", "dc", "segments.csv")


@dataclass(frozen=True)
class Segment:
    id: str
    ward: str
    road_class: str
    lights: int = 0
    kw: float = 0.0


def load_segments(path: str = SEGMENTS_DC) -> List[Segment]:
    with open(path) as f:
        return [Segment(r["segment"], r["ward"], r["road_class"], int(r["lights"]), float(r["kw"]))
                for r in csv.DictReader(f)]


def public_seed(text: str) -> int:
    """A 64-bit seed anyone can recompute from a string published before
    the draw."""
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


@dataclass
class Plan:
    seed_text: str
    waves: int
    start: date
    wave_days: int
    assignment: Dict[str, int]               # segment id -> wave (1-based)

    def wave_start(self, wave: int) -> date:
        return self.start + timedelta(days=self.wave_days * (wave - 1))

    def switched(self, segment_id: str, day: date) -> bool:
        return day >= self.wave_start(self.assignment[segment_id])

    def balance(self, segments: Sequence[Segment], key: str) -> Dict[str, List[int]]:
        """Segments per wave within each value of `key` (ward, road_class)."""
        table: Dict[str, List[int]] = defaultdict(lambda: [0] * self.waves)
        for s in segments:
            table[getattr(s, key)][self.assignment[s.id] - 1] += 1
        return dict(table)

    def to_csv(self, path: str, segments: Sequence[Segment]) -> None:
        with open(path, "w") as f:
            f.write("segment,ward,road_class,lights,wave,switch_on\n")
            for s in sorted(segments, key=lambda s: (self.assignment[s.id], s.ward, s.road_class, s.id)):
                w = self.assignment[s.id]
                f.write(f"{s.id},{s.ward},{s.road_class},{s.lights},{w},{self.wave_start(w).isoformat()}\n")


def stepped_wedge(segments: Sequence[Segment], seed_text: str, waves: int = 4, start: date = date(2027, 1, 4),
                  wave_days: int = 56, strata: Tuple[str, ...] = ("ward", "road_class")) -> Plan:
    """Shuffle each stratum with the public seed and deal it round-robin into
    waves, starting each stratum where the last left off so wave sizes stay
    within one of each other overall."""
    rng = random.Random(public_seed(seed_text))
    groups: Dict[Tuple, List[Segment]] = defaultdict(list)
    for s in segments:
        groups[tuple(getattr(s, k) for k in strata)].append(s)
    assignment: Dict[str, int] = {}
    cursor = 0
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda s: s.id)
        rng.shuffle(members)
        for s in members:
            assignment[s.id] = cursor % waves + 1
            cursor += 1
    return Plan(seed_text, waves, start, wave_days, assignment)


# ------------------------------------------------------------- the brake
def _binom_logpmf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            + k * math.log(p) + (n - k) * math.log1p(-p))


def _binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return min(1.0, sum(math.exp(_binom_logpmf(i, n, p)) for i in range(k, n + 1)))


def _binom_cdf(k: int, n: int, p: float) -> float:
    return min(1.0, sum(math.exp(_binom_logpmf(i, n, p)) for i in range(0, k + 1)))


def _bisect(f, lo: float = 0.0, hi: float = 1.0, iters: int = 60) -> float:
    for _ in range(iters):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) else (lo, mid)
    return (lo + hi) / 2


@dataclass
class RateTest:
    rate_ratio: float
    lo: float
    hi: float
    p_harm: float                            # one-sided: switched segments worse

    def __str__(self) -> str:
        return f"RR {self.rate_ratio:.2f} (95 % CI {self.lo:.2f}-{self.hi:.2f}), one-sided p = {self.p_harm:.3g}"


def rate_ratio_test(events_on: int, exposure_on: float, events_off: int, exposure_off: float) -> RateTest:
    """Exact conditional test of equal Poisson rates. Given the total count,
    the switched segments' share is Binomial(n, E_on / (E_on + E_off))
    under the null; Clopper-Pearson limits on that share give the rate
    ratio's interval."""
    n = events_on + events_off
    p0 = exposure_on / (exposure_on + exposure_off)
    odds = exposure_off / exposure_on
    if n == 0:
        return RateTest(float("nan"), 0.0, math.inf, 1.0)
    p_harm = _binom_sf(events_on, n, p0)
    lo_p = 0.0 if events_on == 0 else _bisect(lambda p: _binom_sf(events_on, n, p) < 0.025)
    hi_p = 1.0 if events_on == n else _bisect(lambda p: _binom_cdf(events_on, n, p) > 0.025)
    to_rr = lambda p: p / (1 - p) * odds if p < 1 else math.inf
    rr = (events_on / exposure_on) / (events_off / exposure_off) if events_off else math.inf
    return RateTest(rr, to_rr(lo_p), to_rr(hi_p), p_harm)


def brake(events_on: int, exposure_on: float, events_off: int, exposure_off: float, looks: int = 4,
          alpha: float = 0.05) -> Tuple[str, RateTest]:
    """'pause' if the switched segments are worse at the Bonferroni-split
    level for this look, else 'continue'."""
    t = rate_ratio_test(events_on, exposure_on, events_off, exposure_off)
    return ("pause" if t.p_harm < alpha / looks else "continue"), t


def exposure_needed(rate: float, rate_ratio: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Segment-nights per arm to detect `rate_ratio` against a baseline
    `rate` (events per segment-night), two-sided, by the normal
    approximation to the log rate ratio."""
    z = NormalDist().inv_cdf(1 - alpha / 2) + NormalDist().inv_cdf(power)
    return z * z * (1 / rate + 1 / (rate * rate_ratio)) / math.log(rate_ratio) ** 2
