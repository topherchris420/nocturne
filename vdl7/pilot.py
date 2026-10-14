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
* **Safety brake.** Before each new wave, night-time crashes (or any harm
  count) on switched segments are compared with not-yet-switched segments
  within each period between wave starts, and the periods are combined by
  an exact stratified test, so the season (winter nights are longer and
  more dangerous than June's) cannot pass for an effect. The error rate is
  split across the looks. A signal pauses the next wave and reverts the
  affected class's bundle; it never waits for the end of the pilot.
* **Power.** `exposure_needed` says how many segment-nights a given
  baseline rate needs to detect a given change, before anyone commits.
"""
from __future__ import annotations

import csv
import hashlib
import math
import os
import random
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import NormalDist
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

SEGMENTS_DC = os.path.join(os.path.dirname(__file__), "..", "data", "dc", "segments.csv")


@dataclass(frozen=True)
class Segment:
    id: str
    ward: str
    road_class: str
    lights: int = 0
    kw: float = 0.0


SEGMENT_COLUMNS = ("segment", "ward", "road_class", "lights", "kw")
PLAN_COLUMNS = ("segment", "ward", "road_class", "lights", "wave", "switch_on")


def load_segments(path: str = SEGMENTS_DC) -> List[Segment]:
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in SEGMENT_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: needs the columns {','.join(SEGMENT_COLUMNS)}; missing {', '.join(missing)}")
        out = []
        for r in reader:
            try:
                out.append(Segment(r["segment"], r["ward"], r["road_class"], int(r["lights"]), float(r["kw"])))
            except (TypeError, ValueError):
                raise ValueError(f"{path}, line {reader.line_num}: lights must be a whole number and kw a "
                                 f"number, got {r.get('lights')!r} and {r.get('kw')!r}") from None
        return out


def _writer(f):
    """CSV rows quoted where a field needs it (a ward named 'Ward 1, North'),
    with the same plain '\\n' line ends as before."""
    return csv.writer(f, lineterminator="\n")


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
        with open(path, "w", newline="") as f:
            out = _writer(f)
            out.writerow(PLAN_COLUMNS)
            for s in sorted(segments, key=lambda s: (self.assignment[s.id], s.ward, s.road_class, s.id)):
                w = self.assignment[s.id]
                out.writerow([s.id, s.ward, s.road_class, s.lights, w, self.wave_start(w).isoformat()])


def load_plan(path: str) -> List[Dict[str, str]]:
    """The rows of a plan CSV that `Plan.to_csv` wrote, checked: every
    column present, every wave a whole number and every switch-on an ISO
    date."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in PLAN_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: not a plan from `nocturne pilot --out` (missing {', '.join(missing)})")
        rows = list(reader)
    for n, r in enumerate(rows, start=2):
        try:
            if int(r["wave"]) < 1:
                raise ValueError
            date.fromisoformat(r["switch_on"])
        except (TypeError, ValueError):
            raise ValueError(f"{path}, row {n}: wave {r['wave']!r} and switch_on {r['switch_on']!r} must be a "
                             f"wave number and a YYYY-MM-DD date") from None
    return rows


def stepped_wedge(segments: Sequence[Segment], seed_text: str, waves: int = 4, start: date = date(2027, 1, 4),
                  wave_days: int = 56, strata: Tuple[str, ...] = ("ward", "road_class")) -> Plan:
    """Shuffle each stratum with the public seed and deal it round-robin into
    waves, starting each stratum where the last left off so wave sizes stay
    within one of each other overall."""
    if waves < 1:
        raise ValueError(f"waves must be at least 1, got {waves}")
    if wave_days < 1:
        raise ValueError(f"wave_days must be at least 1, got {wave_days}")
    ids = [s.id for s in segments]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})[:5]
        raise ValueError(f"segment ids repeat ({', '.join(dup)}): each segment is randomised once")
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


NO_EVIDENCE = RateTest(float("nan"), 0.0, math.inf, 1.0)


def _check(events_on: int, exposure_on: float, events_off: int, exposure_off: float) -> None:
    if min(events_on, events_off) < 0 or min(exposure_on, exposure_off) < 0:
        raise ValueError("counts and exposures cannot be negative")
    if not all(math.isfinite(x) for x in (exposure_on, exposure_off)):
        raise ValueError("exposures must be finite")


def rate_ratio_test(events_on: int, exposure_on: float, events_off: int, exposure_off: float) -> RateTest:
    """Exact conditional test of equal Poisson rates. Given the total count,
    the switched segments' share is Binomial(n, E_on / (E_on + E_off))
    under the null; Clopper-Pearson limits on that share give the rate
    ratio's interval. With no exposure in either arm there is nothing to
    compare, and the result says so (p = 1)."""
    _check(events_on, exposure_on, events_off, exposure_off)
    n = events_on + events_off
    if n == 0 or exposure_on == 0 or exposure_off == 0:
        return NO_EVIDENCE
    p0 = exposure_on / (exposure_on + exposure_off)
    odds = exposure_off / exposure_on
    p_harm = _binom_sf(events_on, n, p0)
    lo_p = 0.0 if events_on == 0 else _bisect(lambda p: _binom_sf(events_on, n, p) < 0.025)
    hi_p = 1.0 if events_on == n else _bisect(lambda p: _binom_cdf(events_on, n, p) > 0.025)
    to_rr = lambda p: p / (1 - p) * odds if p < 1 else math.inf
    rr = (events_on / exposure_on) / (events_off / exposure_off) if events_off else math.inf
    return RateTest(rr, to_rr(lo_p), to_rr(hi_p), p_harm)


# A period of the wedge: (events_on, exposure_on, events_off, exposure_off).
Stratum = Tuple[int, float, int, float]


def _binom_pmf(n: int, p: float) -> Tuple[int, List[float]]:
    """Binomial(n, p) pmf as (first k, values), trimmed where it falls
    below 1e-13 of the mode (p-values far below any brake threshold stay
    exact to many digits), so convolutions of large counts stay quick."""
    if p <= 0.0 or p >= 1.0:
        return (0 if p <= 0.0 else n), [1.0]
    mode = min(n, int((n + 1) * p))
    odds = p / (1.0 - p)
    top = math.exp(_binom_logpmf(mode, n, p))
    up, v, k = [], top, mode                 # pmf(k+1) = pmf(k) (n-k)/(k+1) p/(1-p)
    while k < n:
        v *= (n - k) / (k + 1) * odds
        if v < top * 1e-13:
            break
        up.append(v)
        k += 1
    down, v, k = [], top, mode
    while k > 0:
        v *= k / (n - k + 1) / odds
        if v < top * 1e-13:
            break
        down.append(v)
        k -= 1
    return mode - len(down), down[::-1] + [top] + up


def _sum_pmf(parts: Sequence[Tuple[int, List[float]]]) -> Tuple[int, List[float]]:
    """The pmf of a sum of independent counts, by convolution."""
    off, acc = 0, [1.0]
    for lo, pmf in parts:
        out = [0.0] * (len(acc) + len(pmf) - 1)
        for i, a in enumerate(acc):
            if a:
                out[i:i + len(pmf)] = [o + a * b for o, b in zip(out[i:i + len(pmf)], pmf)]
        off, acc = off + lo, out
    return off, acc


def _tails(strata: Sequence[Tuple[int, float]], t: int, rr: float) -> Tuple[float, float]:
    """(P(T >= t), P(T <= t)) for T = sum of Binomial(n_k, p_k(rr)), with
    p_k(rr) = rr E_on / (rr E_on + E_off), here passed as (n_k, E_on/E_off)."""
    off, pmf = _sum_pmf([_binom_pmf(n, rr * q / (rr * q + 1.0)) for n, q in strata])
    i = t - off
    upper = sum(pmf[max(0, i):]) if i < len(pmf) else 0.0
    lower = sum(pmf[:i + 1]) if i >= 0 else 0.0
    return min(1.0, upper), min(1.0, lower)


def stratified_rate_test(periods: Sequence[Stratum]) -> RateTest:
    """Exact test of a common rate ratio across the wedge's periods.

    Within a period every segment is switched or not for the whole period,
    so on and off share its season. Given each period's total count, the
    switched segments' count is Binomial(n_k, E_on,k / (E_on,k + E_off,k))
    under the null, and the statistic is their sum over periods: its null
    distribution is the convolution of those binomials (the stratified
    conditional test). The estimate is the Mantel-Haenszel rate ratio; the
    interval inverts the same exact distribution. Periods with nobody
    switched, or nobody left to switch, carry no comparison and drop out.
    One period reduces to `rate_ratio_test`."""
    for st in periods:
        _check(*st)
    used = [st for st in periods if st[1] > 0 and st[3] > 0 and st[0] + st[2] > 0]
    if not used:
        return NO_EVIDENCE
    if len(used) == 1:
        return rate_ratio_test(*used[0])
    t = sum(st[0] for st in used)
    strata = [(st[0] + st[2], st[1] / st[3]) for st in used]
    num = sum(a * e0 / (e1 + e0) for a, e1, _b, e0 in used)
    den = sum(b * e1 / (e1 + e0) for _a, e1, b, e0 in used)
    rr = num / den if den else math.inf
    p_harm = _tails(strata, t, 1.0)[0]
    n = sum(k for k, _ in strata)

    x0 = math.log(rr) if 0.0 < rr < math.inf else 0.0

    def limit(side: int) -> float:
        """Where a tail of T is 2.5 %, in RR: the upper tail (side 0) for the
        lower limit, the lower tail (side 1) for the upper. The log tail is
        smooth and monotone in log RR, so bracket it about the estimate and
        close in by the Illinois rule."""
        g = lambda x: math.log(max(_tails(strata, t, math.exp(x))[side], 1e-300) / 0.025)
        a, b = x0 - 0.5, x0 + 0.5
        ga, gb = g(a), g(b)
        while ga * gb > 0 and b - a < 60.0:
            a, b = a - (b - a), b + (b - a)
            ga, gb = g(a), g(b)
        kept = 0
        c = a
        for _ in range(200):                     # a and b always bracket the limit
            c = (a * gb - b * ga) / (gb - ga)
            gc = g(c)
            if gc == 0.0:
                break
            if gc * gb > 0:
                b, gb = c, gc
                if kept == -1:
                    ga /= 2.0
                kept = -1
            else:
                a, ga = c, gc
                if kept == 1:
                    gb /= 2.0
                kept = 1
            if b - a < 1e-10 or abs(gc) < 1e-12:
                break
        return math.exp(c)
    lo_rr = 0.0 if t == 0 else limit(0)
    hi_rr = math.inf if t == n else limit(1)
    return RateTest(rr, lo_rr, hi_rr, p_harm)


def brake(periods: Sequence[Stratum], looks: int = 3, alpha: float = 0.05) -> Tuple[str, RateTest]:
    """'pause' if the switched segments are worse at the Bonferroni-split
    level for this look, else 'continue'. `periods` are every period of the
    wedge so far (see `tally`); a 4-wave wedge has 3 looks, one before each
    wave after the first."""
    if looks < 1:
        raise ValueError("looks must be at least 1")
    t = stratified_rate_test(periods)
    return ("pause" if t.p_harm < alpha / looks else "continue"), t


@dataclass(frozen=True)
class Period:
    start: date
    nights: int
    events_on: int
    exposure_on: float                       # segment-nights
    events_off: int
    exposure_off: float

    @property
    def stratum(self) -> Stratum:
        return (self.events_on, self.exposure_on, self.events_off, self.exposure_off)


def tally(switch_on: Mapping[str, date], events: Iterable[Tuple[str, date]], through: date,
          weight: Optional[Mapping[str, float]] = None) -> Tuple[List[Period], int]:
    """Per-period counts for the brake, from each segment's switch-on date
    and a list of (segment, night) harms: in each period between wave
    starts up to `through`, events and segment-nights on switched and
    not-yet-switched segments. `weight` scales a segment's nights (lights
    or length) if exposure should not count every segment alike. Returns
    the periods and the number of events that fell outside the plan
    (unknown segment, or a night before the first wave or after
    `through`)."""
    starts = sorted(set(switch_on.values()))
    if not starts:
        raise ValueError("the plan has no segments")
    w = weight or {}
    periods: List[Period] = []
    tallies = [[0, 0] for _ in starts]
    skipped = 0
    for seg, night in events:
        when = switch_on.get(seg)
        if when is None or night < starts[0] or night > through:
            skipped += 1
            continue
        tallies[bisect_right(starts, night) - 1][0 if when <= night else 1] += 1
    for i, lo in enumerate(starts):
        hi = min(starts[i + 1] if i + 1 < len(starts) else through + timedelta(days=1), through + timedelta(days=1))
        nights = max(0, (hi - lo).days)
        if nights == 0:
            break
        on = sum(w.get(sg, 1.0) for sg, d in switch_on.items() if d <= lo)
        off = sum(w.get(sg, 1.0) for sg, d in switch_on.items() if d > lo)
        periods.append(Period(lo, nights, tallies[i][0], on * nights, tallies[i][1], off * nights))
    return periods, skipped


def exposure_needed(rate: float, rate_ratio: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Segment-nights per arm to detect `rate_ratio` against a baseline
    `rate` (events per segment-night), two-sided, by the normal
    approximation to the log rate ratio."""
    if not (math.isfinite(rate) and rate > 0):
        raise ValueError(f"baseline rate must be a positive number of events per segment-night, got {rate:g}")
    if not (math.isfinite(rate_ratio) and rate_ratio > 0) or rate_ratio == 1:
        raise ValueError(f"rate ratio must be positive and not 1 (1 is no change to detect), got {rate_ratio:g}")
    if not (0 < alpha < 1 and 0 < power < 1):
        raise ValueError("alpha and power must be between 0 and 1")
    z = NormalDist().inv_cdf(1 - alpha / 2) + NormalDist().inv_cdf(power)
    return z * z * (1 / rate + 1 / (rate * rate_ratio)) / math.log(rate_ratio) ** 2
