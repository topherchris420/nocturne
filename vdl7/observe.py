"""Measurement and verification: did the sky actually get darker?

A city that dims its lights for the sky should be able to show the sky
changed. Sky Quality Meters (SQM-LU-DL, TESS-W and similar photometers on a
library roof or a fire station) log zenith brightness every few minutes in
mag/arcsec^2. This module turns those logs into evidence:

* keep only readings taken in astronomical darkness with the Moon down,
  and only windows where the sky is steady (clouds over a city brighten
  the zenith and make it jump about);
* per night, the *curfew step*: the change in brightness from just before
  23:00 to just after it, the moment the streetlights and every Night Signal
  partner step down;
* the difference in that step between nights before and after Nocturne went
  live, with a bootstrap confidence interval.

The curfew step is a within-night comparison, so season, aerosol, snow
cover and the slow evening decline in the city's other lighting cancel; the
before/after difference removes whatever step the city already had. It is
the cheapest credible measurement of what the programme did to the sky.

The Moon comes from the Astronomical Almanac's low-precision series (about
0.3 deg), checked in EXT-OBS-1 against JPL-grade ephemerides at the 2026
eclipses.
"""
from __future__ import annotations

import csv
import math
import random
import re
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from .clock import POSIX_TZ, julian_day, local_hour, solar_elevation_exact, sun_apparent_longitude_deg, to_local

UTC = timezone.utc
Reading = Tuple[datetime, float]           # (UTC, mag/arcsec^2)


# ------------------------------------------------------------------ Moon
@dataclass
class MoonState:
    alt_deg: float                         # topocentric altitude, no refraction
    az_deg: float                          # from north through east
    illuminated: float                     # fraction of the disk lit, 0-1
    elongation_deg: float                  # geocentric angle from the Sun


def _sin(deg: float) -> float:
    return math.sin(math.radians(deg))


def _cos(deg: float) -> float:
    return math.cos(math.radians(deg))


def moon(utc: datetime, lat: float, lon: float) -> MoonState:
    jd = julian_day(utc)
    t = (jd - 2451545.0) / 36525.0
    lam = (218.32 + 481267.881 * t + 6.29 * _sin(135.0 + 477198.87 * t) - 1.27 * _sin(259.3 - 413335.36 * t)
           + 0.66 * _sin(235.7 + 890534.22 * t) + 0.21 * _sin(269.9 + 954397.74 * t)
           - 0.19 * _sin(357.5 + 35999.05 * t) - 0.11 * _sin(186.5 + 966404.03 * t)) % 360.0
    beta = (5.13 * _sin(93.3 + 483202.02 * t) + 0.28 * _sin(228.2 + 960400.89 * t)
            - 0.28 * _sin(318.3 + 6003.15 * t) - 0.17 * _sin(217.6 - 407332.21 * t))
    parallax = (0.9508 + 0.0518 * _cos(135.0 + 477198.87 * t) + 0.0095 * _cos(259.3 - 413335.36 * t)
                + 0.0078 * _cos(235.7 + 890534.22 * t) + 0.0028 * _cos(269.9 + 954397.74 * t))
    eps = 23.439291 - 0.0130042 * t
    l_ = _cos(beta) * _cos(lam)
    m_ = _cos(eps) * _cos(beta) * _sin(lam) - _sin(eps) * _sin(beta)
    n_ = _sin(eps) * _cos(beta) * _sin(lam) + _cos(eps) * _sin(beta)
    ra = math.degrees(math.atan2(m_, l_)) % 360.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, n_))))
    gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t - t ** 3 / 38710000.0) % 360.0
    ha = (gmst + lon - ra) % 360.0
    alt = math.degrees(math.asin(_sin(lat) * _sin(dec) + _cos(lat) * _cos(dec) * _cos(ha)))
    alt -= math.degrees(math.asin(_sin(parallax) * _cos(alt)))
    az = math.degrees(math.atan2(-_cos(dec) * _sin(ha), _sin(dec) * _cos(lat) - _cos(dec) * _sin(lat) * _cos(ha))) % 360.0
    elong = math.degrees(math.acos(max(-1.0, min(1.0, _cos(beta) * _cos(lam - sun_apparent_longitude_deg(utc))))))
    return MoonState(alt, az, (1.0 - _cos(elong)) / 2.0, elong)


# ------------------------------------------------------------- readings
def read_sqm(path: str) -> List[Reading]:
    """A photometer log: the IDA/NSBM text format the SQM-LU-DL and TESS-W
    write (semicolon-separated, '#' header naming the columns, UTC first),
    or a CSV with a header holding a UTC time column and an msas column."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    data = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    if not data:
        return []
    if ";" in data[0]:
        msas_col = None
        for ln in lines:
            if ln.startswith("#") and "MSAS" in ln.upper() and "," in ln:
                names = [x.strip().upper() for x in ln.lstrip("# ").split(",")]
                if "MSAS" in names:
                    msas_col = names.index("MSAS")
        rows = [[p.strip() for p in ln.split(";")] for ln in data]
        if msas_col is None and "MSAS" in [p.upper() for p in rows[0]]:     # a header row without the '#'
            msas_col = [p.upper() for p in rows[0]].index("MSAS")
            rows = rows[1:]
        if not rows:
            return []
        if msas_col is None:                 # no header: one column for the whole file
            msas_col = _msas_column(rows, path)
        out = []
        for parts in rows:
            try:
                out.append((_utc(parts[0]), float(parts[msas_col])))
            except (ValueError, IndexError, TypeError):
                continue
        return out
    rows = list(csv.DictReader(data))           # comment lines are already out
    if not rows:
        return []
    keys = {k.lower().strip(): k for k in rows[0] if k is not None}
    tkey = next((keys[k] for k in keys if k in ("utc", "time", "timestamp", "datetime", "date_utc", "utc_time")), None)
    mkey = next((keys[k] for k in keys if k in ("msas", "mpsas", "sqm", "mag", "brightness")), None)
    if tkey is None or mkey is None:
        raise ValueError(f"{path}: need a UTC time column and an msas column, got {list(rows[0])}")
    out = []
    for r in rows:
        try:
            out.append((_utc(r[tkey]), float(r[mkey])))
        except (ValueError, TypeError):
            continue
    return out


_IDA_HEADER_HINT = ("add the IDA column header line, e.g. "
                    "'# UTC Date & Time, Local Date & Time, Temperature, Counts, Frequency, MSAS'")


def _msas_column(rows: Sequence[Sequence[str]], path: str) -> int:
    """The sky-brightness column of a log without its IDA header, decided
    once for the whole file. A candidate holds 10-25 mag/arcsec^2 in at
    least half the rows. Columns that never change (a TESS-W's zero point,
    a constant temperature or record type) are set aside when one that does
    change exists, since the sky always drifts; of the rest the rightmost
    wins, as MSAS comes after the temperatures and frequency in the
    SQM-LU-DL and TESS-W layouts. When nothing tells the candidates apart,
    the file needs its header."""
    width = max((len(p) for p in rows), default=0)
    cands: Dict[int, List[float]] = {}
    for i in range(1, width):
        vals = []
        for parts in rows:
            try:
                v = float(parts[i])
            except (ValueError, IndexError):
                continue
            if 10.0 <= v <= 25.0:
                vals.append(v)
        if vals and 2 * len(vals) >= len(rows):
            cands[i] = vals
    if not cands:
        raise ValueError(f"{path}: no header names the MSAS column and no column holds sky brightness "
                         f"(10-25 mag/arcsec^2); {_IDA_HEADER_HINT}")
    varying = [i for i, vals in cands.items() if max(vals) > min(vals)]
    if varying:
        return max(varying)
    if len(cands) == 1:
        return next(iter(cands))
    raise ValueError(f"{path}: no header names the MSAS column, and fields {', '.join(str(i + 1) for i in cands)} "
                     f"could each be it (none changes from reading to reading); {_IDA_HEADER_HINT}")


def _utc(text: str) -> datetime:
    t = datetime.fromisoformat(re.sub(r"Z$", "+00:00", text.strip()))
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def write_ida(readings: Sequence[Reading], path: str, tz: str = POSIX_TZ, name: str = "synthetic") -> None:
    """Readings in the IDA/NSBM text format (for tests and data exchange)."""
    with open(path, "w") as f:
        f.write("# Light Pollution Monitoring Data Format 1.0\n")
        f.write(f"# Device type: {name}\n")
        f.write("# UTC Date & Time, Local Date & Time, Temperature, Voltage, MSAS, Record type\n")
        f.write("# YYYY-MM-DDTHH:mm:ss.fff;YYYY-MM-DDTHH:mm:ss.fff;Celsius;Volts;mag/arcsec^2;0=not-averaged\n")
        f.write("# END OF HEADER\n")
        for t, m in readings:
            loc = to_local(t, tz)
            f.write(f"{t.strftime('%Y-%m-%dT%H:%M:%S.000')};{loc.strftime('%Y-%m-%dT%H:%M:%S.000')};10.0;5.00;{m:.2f};0\n")


# --------------------------------------------------------------- filters
def dark(readings: Sequence[Reading], lat: float, lon: float, sun_max: float = -18.0,
         moon_max: float = -5.0) -> List[Reading]:
    """Astronomical darkness with the Moon below `moon_max`."""
    return [(t, m) for t, m in readings
            if solar_elevation_exact(lat, lon, t) < sun_max and moon(t, lat, lon).alt_deg < moon_max]


def steady(readings: Sequence[Reading], half_window: int = 2, max_std: float = 0.05,
           max_gap_s: float = 900.0) -> List[Reading]:
    """Readings whose neighbours within +-half_window samples (and without a
    gap longer than `max_gap_s`) agree to `max_std` mag: a clear sky."""
    out = []
    rs = sorted(readings)
    for i, (t, m) in enumerate(rs):
        lo, hi = max(0, i - half_window), min(len(rs), i + half_window + 1)
        win = rs[lo:hi]
        if len(win) < 2 * half_window + 1:
            continue
        if any((b[0] - a[0]).total_seconds() > max_gap_s for a, b in zip(win, win[1:])):
            continue
        if statistics.pstdev(x for _, x in win) <= max_std:
            out.append((t, m))
    return out


# ------------------------------------------------------------- estimators
def _evening_date(t: datetime, tz: str) -> date:
    loc = to_local(t, tz)
    return (loc - timedelta(hours=12)).date()


def nightly(readings: Sequence[Reading], tz: str = POSIX_TZ, hours: Tuple[float, float] = (22.0, 2.0),
            min_n: int = 5, max_std: Optional[float] = 0.05) -> Dict[date, float]:
    """Median brightness per night within local `hours` (may wrap midnight).
    A night whose readings in the window scatter by more than `max_std` mag
    about their own trend is cloudy there and is left out."""
    buckets: Dict[date, List[Reading]] = {}
    for t, m in readings:
        h = local_hour(t, tz)
        h0, h1 = hours
        inside = (h0 <= h < h1) if h0 < h1 else (h >= h0 or h < h1)
        if inside:
            buckets.setdefault(_evening_date(t, tz), []).append((t, m))
    out = {}
    for d, rs in buckets.items():
        if len(rs) < min_n:
            continue
        if max_std is not None and _detrended_std(rs) > max_std:
            continue
        out[d] = statistics.median(m for _, m in rs)
    return out


def _detrended_std(rs: Sequence[Reading]) -> float:
    """Scatter about a straight line in time: a clear sky drifts smoothly,
    a cloudy one jumps."""
    t0 = rs[0][0]
    xs = [(t - t0).total_seconds() / 3600.0 for t, _ in rs]
    ys = [m for _, m in rs]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    return statistics.pstdev(y - (my + slope * (x - mx)) for x, y in zip(xs, ys))


def curfew_steps(readings: Sequence[Reading], tz: str = POSIX_TZ, before: Tuple[float, float] = (22.0, 22.92),
                 after: Tuple[float, float] = (23.25, 24.0), min_n: int = 5,
                 max_std: Optional[float] = 0.05) -> Dict[date, float]:
    """Per night: median msas just after the 23:00 curfew minus just before
    it. Positive means the sky got darker when the curfew began. Each
    window is screened for clouds on its own, so the step itself never
    counts as unsteadiness."""
    pre = nightly(readings, tz, before, min_n, max_std)
    post = nightly(readings, tz, after, min_n, max_std)
    return {d: post[d] - pre[d] for d in pre if d in post}


@dataclass
class Estimate:
    effect: float
    lo: float
    hi: float
    n_before: int
    n_after: int

    def __str__(self) -> str:
        return f"{self.effect:+.3f} mag (95 % CI {self.lo:+.3f} to {self.hi:+.3f}; {self.n_before} + {self.n_after} nights)"


def difference(before: Dict[date, float], after: Dict[date, float], n_boot: int = 2000, seed: int = 1) -> Estimate:
    """Mean of `after` minus mean of `before`, with a percentile bootstrap
    over nights. Applied to curfew steps it is a difference-in-differences."""
    a, b = list(before.values()), list(after.values())
    if len(a) < 3 or len(b) < 3:
        raise ValueError(f"need at least 3 usable nights on each side, have {len(a)} and {len(b)}")
    rng = random.Random(seed)
    eff = statistics.fmean(b) - statistics.fmean(a)
    boots = sorted(statistics.fmean(rng.choices(b, k=len(b))) - statistics.fmean(rng.choices(a, k=len(a)))
                   for _ in range(n_boot))
    return Estimate(eff, boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1], len(a), len(b))


def verify(readings: Sequence[Reading], go_live: date, lat: float, lon: float, tz: str = POSIX_TZ) -> dict:
    """The whole pipeline for one station: filter, step per night, and the
    before/after difference in the curfew step and in the post-curfew sky."""
    good = dark(readings, lat, lon)
    steps = curfew_steps(good, tz)
    late = nightly(good, tz, (23.25, 2.0), max_std=0.08)
    split = lambda d: ({k: v for k, v in d.items() if k < go_live}, {k: v for k, v in d.items() if k >= go_live})
    s0, s1 = split(steps)
    l0, l1 = split(late)
    out = {"readings": len(readings), "dark": len(good), "nights_with_step": len(steps), "notes": []}
    for key, (b, a) in (("curfew_step_change", (s0, s1)), ("post_curfew_change", (l0, l1))):
        try:
            out[key] = difference(b, a)
        except ValueError as e:              # one estimate short of nights must not lose the other
            out[key] = None
            out["notes"].append(f"{key}: {e}")
    return out
