"""Astronomical clock, daylight-saving rules, RTC holdover and photocell.

The node never asks the host operating system for the time. Civil time comes
from a POSIX TZ rule compiled into firmware (R-CLK-1 checks DC's against the
IANA database; EXT-CLK-4 checks a dozen other cities'), dusk and dawn from the
NOAA solar-position algorithm (R-CLK-2), and whether the real-time clock may
be believed from a drift budget (R-CLK-3). Nothing here is specific to DC
except the defaults: a node anywhere carries its own latitude, longitude and
rule, and above the Arctic Circle the lights simply follow the sun.
"""
from __future__ import annotations

import calendar
import math
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional, Tuple

DC_LAT = 38.8977
DC_LON = -77.0365

NIGHT_ELEVATION_DEG = -3.0       # lights-on threshold used by the profile clock
SUNRISE_ELEVATION_DEG = -0.833   # geometric sunrise/sunset incl. refraction

# POSIX TZ rule compiled into firmware: DC's by default, any city's by
# `NodeConfig.tz`. Second Sunday in March 02:00 to first Sunday in November 02:00.
POSIX_TZ = "EST5EDT,M3.2.0,M11.1.0"
UTC = timezone.utc


# --------------------------------------------------------------------------
# Civil time: POSIX TZ rules (IEEE Std 1003.1, with the RFC 8536 extensions
# that the IANA database emits in its TZif footers: quoted names like <-04>,
# transition hours outside 0-24 and half-hour offsets)
# --------------------------------------------------------------------------
_NAME = re.compile(r"<[A-Za-z0-9+\-]+>|[A-Za-z]{3,}")
_OFFSET = re.compile(r"[+-]?\d{1,3}(?::\d{1,2}(?::\d{1,2})?)?")


def _hms(text: str) -> int:
    """'5', '-3:30', '+167:00:00' -> seconds."""
    sign = -1 if text.startswith("-") else 1
    parts = [int(p) for p in text.lstrip("+-").split(":")]
    parts += [0] * (3 - len(parts))
    if parts[0] > 167 or parts[1] > 59 or parts[2] > 59:
        raise ValueError(f"time {text!r} out of range")
    return sign * (parts[0] * 3600 + parts[1] * 60 + parts[2])


@dataclass(frozen=True)
class TransitionRule:
    """One end of daylight time: `Mm.w.d`, `Jn` or `n`, with a local time."""
    kind: str                # "M" month/week/day, "J" Julian 1-365 without Feb 29, "N" zero-based day
    a: int = 0               # M: month       J/N: day number
    b: int = 0               # M: week 1-5 (5 = last)
    c: int = 0               # M: weekday 0-6, Sunday = 0
    secs: int = 7200         # local time of day; RFC 8536 allows -167 h to +167 h

    def local(self, year: int) -> datetime:
        """The transition as a naive local wall time in `year`."""
        if self.kind == "M":
            first = datetime(year, self.a, 1)
            sunday_based = (first.weekday() + 1) % 7
            day = 1 + (self.c - sunday_based) % 7 + 7 * (self.b - 1)
            last = calendar.monthrange(year, self.a)[1]
            while day > last:                        # week 5 means the last such weekday
                day -= 7
            base = datetime(year, self.a, day)
        elif self.kind == "J":
            base = datetime(year, 1, 1) + timedelta(days=self.a - 1)
            if calendar.isleap(year) and self.a >= 60:   # Feb 29 is never counted
                base += timedelta(days=1)
        else:
            base = datetime(year, 1, 1) + timedelta(days=self.a)
        return base + timedelta(seconds=self.secs)


@dataclass(frozen=True)
class PosixTZ:
    """A parsed POSIX TZ rule. Offsets are seconds *east* of UTC (the POSIX
    text counts west, so EST5 is -18000 here)."""
    text: str
    std_name: str
    std_off: int
    dst_name: Optional[str] = None
    dst_off: Optional[int] = None
    start: Optional[TransitionRule] = None
    end: Optional[TransitionRule] = None

    @property
    def has_dst(self) -> bool:
        return self.dst_name is not None

    def is_dst(self, utc: datetime) -> bool:
        if not self.has_dst:
            return False
        y = utc.year
        for year in (y - 1, y, y + 1):
            start, end = _dst_bounds(self, year)
            if end <= start:                         # southern hemisphere: spans the new year
                end = _dst_bounds(self, year + 1)[1]
            if start <= utc < end:
                return True
        return False

    def utcoffset_s(self, utc: datetime) -> int:
        return self.dst_off if self.is_dst(utc) else self.std_off    # type: ignore[return-value]

    def to_local(self, utc: datetime) -> datetime:
        return (utc + timedelta(seconds=self.utcoffset_s(utc))).replace(tzinfo=None)

    def to_utc(self, local: datetime) -> datetime:
        """Inverse of `to_local`. The repeated fall-back hour resolves to
        daylight time; the skipped spring-forward hour to standard time."""
        local = local.replace(tzinfo=None)
        offsets = (self.dst_off, self.std_off) if self.has_dst else (self.std_off,)
        for off in offsets:
            cand = (local - timedelta(seconds=off)).replace(tzinfo=UTC)
            if self.to_local(cand) == local:
                return cand
        return (local - timedelta(seconds=self.std_off)).replace(tzinfo=UTC)


@lru_cache(maxsize=1024)
def _dst_bounds(tz: PosixTZ, year: int) -> Tuple[datetime, datetime]:
    """[start, end) of daylight time that begins in `year`, in UTC. The start
    is stated in standard time and the end in daylight time."""
    start = (tz.start.local(year) - timedelta(seconds=tz.std_off)).replace(tzinfo=UTC)     # type: ignore[union-attr]
    end = (tz.end.local(year) - timedelta(seconds=tz.dst_off)).replace(tzinfo=UTC)         # type: ignore[union-attr,arg-type]
    return start, end


def _rule(text: str) -> TransitionRule:
    date_part, _, time_part = text.partition("/")
    secs = _hms(time_part) if time_part else 7200
    if date_part.startswith("M"):
        m, w, d = (int(x) for x in date_part[1:].split("."))
        if not (1 <= m <= 12 and 1 <= w <= 5 and 0 <= d <= 6):
            raise ValueError(f"bad rule {text!r}")
        return TransitionRule("M", m, w, d, secs)
    if date_part.startswith("J"):
        n = int(date_part[1:])
        if not 1 <= n <= 365:
            raise ValueError(f"bad rule {text!r}")
        return TransitionRule("J", n, secs=secs)
    n = int(date_part)
    if not 0 <= n <= 365:
        raise ValueError(f"bad rule {text!r}")
    return TransitionRule("N", n, secs=secs)


@lru_cache(maxsize=256)
def parse_posix_tz(text: str) -> PosixTZ:
    """Parse a POSIX TZ string such as 'EST5EDT,M3.2.0,M11.1.0',
    'ACST-9:30ACDT,M10.1.0,M4.1.0/3' or '<-04>4<-03>,M9.1.6/24,M4.1.6/24'.
    A daylight name without rules gets the US rules, as glibc does."""
    s = text.strip()
    try:
        m = _NAME.match(s)
        std_name, pos = m.group(0), m.end()                       # type: ignore[union-attr]
        m = _OFFSET.match(s, pos)
        std_off, pos = -_hms(m.group(0)), m.end()                 # type: ignore[union-attr]
        if pos == len(s):
            return PosixTZ(text, std_name, std_off)
        m = _NAME.match(s, pos)
        dst_name, pos = m.group(0), m.end()                       # type: ignore[union-attr]
        dst_off = std_off + 3600
        m = _OFFSET.match(s, pos)
        if m and m.end() > pos:
            dst_off, pos = -_hms(m.group(0)), m.end()
        rules = s[pos:]
        if not rules:
            rules = ",M3.2.0,M11.1.0"
        if not rules.startswith(","):
            raise ValueError("expected ',' before the rules")
        start_txt, end_txt = rules[1:].split(",")
        return PosixTZ(text, std_name, std_off, dst_name, dst_off, _rule(start_txt), _rule(end_txt))
    except (AttributeError, ValueError, TypeError) as e:
        raise ValueError(f"not a POSIX TZ rule: {text!r} ({e})") from None


def posix_tz_from_iana(name: str) -> str:
    """The POSIX rule the IANA database itself compiles for a zone (the TZif
    footer), for commissioning: `posix_tz_from_iana('Europe/Paris')`."""
    import zoneinfo
    blob = None
    for base in zoneinfo.TZPATH:
        path = os.path.join(base, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                blob = f.read()
            break
    if blob is None:                                  # Windows: the `tzdata` package
        try:
            from importlib import resources
            blob = resources.files("tzdata.zoneinfo").joinpath(*name.split("/")).read_bytes()
        except Exception:
            raise LookupError(f"zone {name!r} not found in {zoneinfo.TZPATH} or the tzdata package") from None
    if not blob.startswith(b"TZif") or blob[4:5] < b"2":
        raise LookupError(f"zone {name!r}: TZif version 1 has no POSIX footer")
    footer = blob.rstrip(b"\n").rsplit(b"\n", 1)[-1].decode("ascii")
    parse_posix_tz(footer)
    return footer


def _tz(tz) -> PosixTZ:
    return tz if isinstance(tz, PosixTZ) else parse_posix_tz(tz)


def is_dst(utc: datetime, tz=POSIX_TZ) -> bool:
    return _tz(tz).is_dst(utc)


def utc_offset_hours(utc: datetime, tz=POSIX_TZ) -> float:
    return _tz(tz).utcoffset_s(utc) / 3600.0


def to_local(utc: datetime, tz=POSIX_TZ) -> datetime:
    """Local civil time as a naive datetime."""
    return _tz(tz).to_local(utc)


def local_hour(utc: datetime, tz=POSIX_TZ) -> float:
    loc = to_local(utc, tz)
    return loc.hour + loc.minute / 60.0 + loc.second / 3600.0


def local_to_utc(local: datetime, tz=POSIX_TZ) -> datetime:
    """Inverse of to_local. The ambiguous fall-back hour resolves to daylight
    time; the spring-forward gap resolves to standard time."""
    return _tz(tz).to_utc(local)


def parse_local(s: str, tz=POSIX_TZ) -> datetime:
    """'2026-10-13 23:30' or ISO 'T' form, local civil time -> aware UTC."""
    return local_to_utc(datetime.fromisoformat(s), tz)


# --------------------------------------------------------------------------
# Solar position (NOAA General Solar Position Calculations)
# --------------------------------------------------------------------------
def julian_day(utc: datetime) -> float:
    y, m, d = utc.year, utc.month, utc.day
    frac = (utc.hour + utc.minute / 60 + utc.second / 3600 + utc.microsecond / 3.6e9) / 24
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5 + frac


def sun_apparent_longitude_deg(utc: datetime) -> float:
    """The Sun's apparent ecliptic longitude (NOAA series), for the Moon's
    phase in vdl7.observe."""
    jc = (julian_day(utc) - 2451545.0) / 36525.0
    l0 = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360.0
    m = math.radians(357.52911 + jc * (35999.05029 - 0.0001537 * jc))
    c = (math.sin(m) * (1.914602 - jc * (0.004817 + 0.000014 * jc)) + math.sin(2 * m) * (0.019993 - 0.000101 * jc)
         + math.sin(3 * m) * 0.000289)
    omega = 125.04 - 1934.136 * jc
    return (l0 + c - 0.00569 - 0.00478 * math.sin(math.radians(omega))) % 360.0


def _solar_elevation(lat: float, lon: float, jd: float, minutes_utc: float) -> float:
    jc = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360.0
    m = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * jc)
         + math.sin(3 * mr) * 0.000289)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(app_long)))
    y = math.tan(math.radians(eps) / 2) ** 2
    l0r = math.radians(l0)
    eqtime = 4 * math.degrees(
        y * math.sin(2 * l0r) - 2 * e * math.sin(mr) + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    tst = (minutes_utc + eqtime + 4 * lon) % 1440.0
    ha = tst / 4.0 - 180.0
    latr = math.radians(lat)
    cos_zen = math.sin(latr) * math.sin(decl) + math.cos(latr) * math.cos(decl) * math.cos(math.radians(ha))
    cos_zen = max(-1.0, min(1.0, cos_zen))
    # Geometric elevation. Thresholds in this module are geometric too, so the
    # -0.833 deg sunrise/sunset value already carries refraction and the solar
    # semidiameter, exactly as the NOAA sunrise calculation does.
    return 90.0 - math.degrees(math.acos(cos_zen))


def solar_elevation_exact(lat: float, lon: float, utc: datetime) -> float:
    minutes = utc.hour * 60 + utc.minute + utc.second / 60 + utc.microsecond / 6e7
    return _solar_elevation(lat, lon, julian_day(utc), minutes)


@lru_cache(maxsize=65536)
def _elev_cached(lat: float, lon: float, minute_key: int) -> float:
    utc = datetime.fromtimestamp(minute_key * 60, UTC)
    return solar_elevation_exact(lat, lon, utc)


def solar_elevation_deg(lat: float, lon: float, utc: datetime) -> float:
    """Elevation of the sun in degrees, cached per minute (what the 1 Hz loop
    uses; a one-minute quantisation moves dusk by at most 15 arc-seconds)."""
    return _elev_cached(round(lat, 4), round(lon, 4), int(utc.timestamp() // 60))


def next_crossing(lat: float, lon: float, start: datetime, threshold: float,
                  descending: bool, max_hours: float = 36.0, coarse_s: int = 600
                  ) -> Optional[datetime]:
    """First instant after `start` at which the elevation crosses `threshold`
    in the requested direction, to one-second resolution."""
    t = start
    prev = solar_elevation_exact(lat, lon, t)
    end = start + timedelta(hours=max_hours)
    while t < end:
        t2 = t + timedelta(seconds=coarse_s)
        e2 = solar_elevation_exact(lat, lon, t2)
        hit = (prev >= threshold > e2) if descending else (prev < threshold <= e2)
        if hit:
            lo, hi = t, t2
            for _ in range(20):
                mid = lo + (hi - lo) / 2
                em = solar_elevation_exact(lat, lon, mid)
                before = (em >= threshold) if descending else (em < threshold)
                if before:
                    lo = mid
                else:
                    hi = mid
            return hi.replace(microsecond=0)
        t, prev = t2, e2
    return None


@lru_cache(maxsize=4096)
def night_bounds(lat: float, lon: float, local_date: date, threshold: float = NIGHT_ELEVATION_DEG,
                 tz: str = POSIX_TZ) -> Tuple[Optional[datetime], Optional[datetime]]:
    """(dusk, dawn) in UTC for the night that starts on `local_date`. Either
    is None where the sun does not cross `threshold`: no dusk under the
    midnight sun or in polar night, no dawn when polar night begins."""
    noon = local_to_utc(datetime(local_date.year, local_date.month, local_date.day, 12), tz)
    dusk = next_crossing(lat, lon, noon, threshold, descending=True)
    if dusk is None:
        return None, None
    return dusk, next_crossing(lat, lon, dusk, threshold, descending=False)


def sun_times(lat: float, lon: float, local_date: date, tz: str = POSIX_TZ
              ) -> Tuple[Optional[datetime], Optional[datetime]]:
    """(sunrise, sunset) as naive local datetimes for a civil date; None
    where the sun does not rise or set."""
    midnight = local_to_utc(datetime(local_date.year, local_date.month, local_date.day, 0), tz)
    rise = next_crossing(lat, lon, midnight, SUNRISE_ELEVATION_DEG, descending=False, max_hours=24.0)
    if rise is None:
        return None, None
    sset = next_crossing(lat, lon, rise, SUNRISE_ELEVATION_DEG, descending=True)
    return to_local(rise, tz), (to_local(sset, tz) if sset is not None else None)


def learned_night(lat: float, lon: float, local_date: date, tz: str = POSIX_TZ
                  ) -> Optional[Tuple[float, float]]:
    """(dark-midpoint local hour, night length h) for the night of local_date —
    the values the node writes to flash after each clocked night. None when
    the sun makes no ordinary night that date (polar day or polar night)."""
    dusk, dawn = night_bounds(lat, lon, local_date, tz=tz)
    if dusk is None or dawn is None:
        return None
    length_h = (dawn - dusk).total_seconds() / 3600.0
    mid = (local_hour(dusk, tz) + length_h / 2.0) % 24.0
    return mid, length_h


# --------------------------------------------------------------------------
# RTC holdover model (Section 5.2, R-CLK-3)
# --------------------------------------------------------------------------
@dataclass
class RtcHoldover:
    """TCXO real-time clock with a drift budget.

    The clock is trusted while drift_ppm x seconds-since-sync stays under the
    5-minute budget: at 3 ppm that is just over three years. It is never
    trusted before its first sync. A supercapacitor holds the clock for seven
    days without mains; a longer cut resets it.

    Separately from wall time, the RTC counter keeps running across short
    cuts whether or not it was ever synced. `raw()` and `epoch` let SAFE mode
    measure how long the power was off without trusting the absolute time;
    `epoch` changes whenever the counter itself was lost."""
    drift_ppm: float = 3.0
    trust_budget_s: float = 300.0
    holdover_days: float = 7.0
    synced: bool = False
    utc_at_sync: Optional[datetime] = None
    mono_at_sync: float = 0.0
    age_before_mono_s: float = 0.0   # drift accumulated across reboots
    epoch: int = 0                   # bumps on every RTC reset
    _raw_base: float = 0.0
    _raw_mono_base: float = 0.0

    def raw(self, mono: float) -> float:
        """Seconds counted by the RTC since its last reset."""
        return self._raw_base + (mono - self._raw_mono_base)

    def sync(self, mono: float, utc: datetime) -> None:
        self.synced = True
        self.utc_at_sync = utc
        self.mono_at_sync = mono
        self.age_before_mono_s = 0.0

    def age_s(self, mono: float) -> float:
        if not self.synced:
            return math.inf
        return self.age_before_mono_s + (mono - self.mono_at_sync)

    def error_bound_s(self, mono: float) -> float:
        if not self.synced:
            return math.inf
        return self.drift_ppm * 1e-6 * self.age_s(mono)

    def trusted(self, mono: float) -> bool:
        return self.synced and self.error_bound_s(mono) < self.trust_budget_s

    def utc_now(self, mono: float) -> Optional[datetime]:
        if not self.synced:
            return None
        return self.utc_at_sync + timedelta(seconds=mono - self.mono_at_sync)

    def power_cycle(self, mono_at_cut: float, outage_s: float) -> None:
        """Mains lost at node-monotonic `mono_at_cut` for `outage_s`; the
        monotonic clock restarts at zero on the far side."""
        if outage_s > self.holdover_days * 86400.0:
            self.reset()
            return
        self._raw_base = self.raw(mono_at_cut) + outage_s
        self._raw_mono_base = 0.0
        if not self.synced:
            return
        elapsed = (mono_at_cut - self.mono_at_sync) + outage_s
        self.utc_at_sync = self.utc_at_sync + timedelta(seconds=elapsed)
        self.age_before_mono_s += elapsed
        self.mono_at_sync = 0.0

    def reset(self) -> None:
        """Supercap drained: wall time and the counter are both gone."""
        self.synced = False
        self.utc_at_sync = None
        self.mono_at_sync = 0.0
        self.age_before_mono_s = 0.0
        self.epoch += 1
        self._raw_base = 0.0
        self._raw_mono_base = 0.0


# --------------------------------------------------------------------------
# Photocell with hysteresis and debounce (Section 6.1)
# --------------------------------------------------------------------------
@dataclass
class Photocell:
    """15 lx on / 40 lx off, 60 s debounce. `dark` is the debounced state."""
    on_lx: float = 15.0
    off_lx: float = 40.0
    debounce_s: float = 60.0
    dark: Optional[bool] = None
    _raw: Optional[bool] = None
    _raw_since: float = 0.0
    last_lx: float = float("nan")

    def sample(self, lx: float, mono: float) -> Optional[bool]:
        """Feed one reading. Returns True on a light->dark flip, False on a
        dark->light flip, None when nothing changed."""
        self.last_lx = lx
        if self.dark is None:                       # power-on read, no debounce
            self.dark = lx < self.on_lx
            self._raw, self._raw_since = self.dark, mono
            return None
        want = self.dark
        if self.dark and lx > self.off_lx:
            want = False
        elif not self.dark and lx < self.on_lx:
            want = True
        if want != self._raw:
            self._raw, self._raw_since = want, mono
        if want != self.dark and mono - self._raw_since >= self.debounce_s:
            self.dark = want
            return want
        return None
