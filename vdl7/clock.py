"""Astronomical clock, US daylight-saving rule, RTC holdover and photocell.

The node never asks the host operating system for the time. Civil time comes
from a POSIX rule compiled into firmware (R-CLK-1 checks it against the IANA
database), dusk and dawn from the NOAA solar-position algorithm (R-CLK-2), and
whether the real-time clock may be believed from a drift budget (R-CLK-3).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional, Tuple

DC_LAT = 38.8977
DC_LON = -77.0365

NIGHT_ELEVATION_DEG = -3.0       # lights-on threshold used by the profile clock
SUNRISE_ELEVATION_DEG = -0.833   # geometric sunrise/sunset incl. refraction

# POSIX TZ string compiled into firmware. Second Sunday in March 02:00 to
# first Sunday in November 02:00.
POSIX_TZ = "EST5EDT,M3.2.0,M11.1.0"
STD_OFFSET_H = -5
DST_OFFSET_H = -4
UTC = timezone.utc


# --------------------------------------------------------------------------
# Civil time
# --------------------------------------------------------------------------
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime:
    """n-th weekday (0=Mon .. 6=Sun) of a month as a naive local midnight."""
    first = datetime(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    return first + timedelta(days=delta + 7 * (n - 1))


@lru_cache(maxsize=128)
def dst_window_utc(year: int) -> Tuple[datetime, datetime]:
    """[start, end) of daylight time for a year, in UTC."""
    start_local = _nth_weekday(year, 3, 6, 2).replace(hour=2)   # 02:00 EST
    end_local = _nth_weekday(year, 11, 6, 1).replace(hour=2)    # 02:00 EDT
    start_utc = (start_local - timedelta(hours=STD_OFFSET_H)).replace(tzinfo=UTC)
    end_utc = (end_local - timedelta(hours=DST_OFFSET_H)).replace(tzinfo=UTC)
    return start_utc, end_utc


def is_dst(utc: datetime) -> bool:
    start, end = dst_window_utc(utc.year)
    return start <= utc < end


def utc_offset_hours(utc: datetime) -> int:
    return DST_OFFSET_H if is_dst(utc) else STD_OFFSET_H


def to_local(utc: datetime) -> datetime:
    """Local civil time as a naive datetime."""
    return (utc + timedelta(hours=utc_offset_hours(utc))).replace(tzinfo=None)


def local_hour(utc: datetime) -> float:
    loc = to_local(utc)
    return loc.hour + loc.minute / 60.0 + loc.second / 3600.0


def local_to_utc(local: datetime) -> datetime:
    """Inverse of to_local. The ambiguous fall-back hour resolves to daylight
    time; the spring-forward gap resolves to standard time."""
    local = local.replace(tzinfo=None)
    for off in (DST_OFFSET_H, STD_OFFSET_H):
        cand = (local - timedelta(hours=off)).replace(tzinfo=UTC)
        if to_local(cand) == local:
            return cand
    return (local - timedelta(hours=STD_OFFSET_H)).replace(tzinfo=UTC)


def parse_local(s: str) -> datetime:
    """'2026-10-13 23:30' or ISO 'T' form, local civil time -> aware UTC."""
    return local_to_utc(datetime.fromisoformat(s))


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
def night_bounds(lat: float, lon: float, local_date: date,
                 threshold: float = NIGHT_ELEVATION_DEG) -> Tuple[datetime, datetime]:
    """(dusk, dawn) in UTC for the night that starts on `local_date`."""
    noon = local_to_utc(datetime(local_date.year, local_date.month, local_date.day, 12))
    dusk = next_crossing(lat, lon, noon, threshold, descending=True)
    dawn = next_crossing(lat, lon, dusk, threshold, descending=False)
    return dusk, dawn


def sun_times(lat: float, lon: float, local_date: date) -> Tuple[datetime, datetime]:
    """(sunrise, sunset) as naive local datetimes for a civil date."""
    midnight = local_to_utc(datetime(local_date.year, local_date.month, local_date.day, 0))
    rise = next_crossing(lat, lon, midnight, SUNRISE_ELEVATION_DEG, descending=False)
    sset = next_crossing(lat, lon, rise, SUNRISE_ELEVATION_DEG, descending=True)
    return to_local(rise), to_local(sset)


def learned_night(lat: float, lon: float, local_date: date) -> Tuple[float, float]:
    """(dark-midpoint local hour, night length h) for the night of local_date —
    the values the node writes to flash after each clocked night."""
    dusk, dawn = night_bounds(lat, lon, local_date)
    length_h = (dawn - dusk).total_seconds() / 3600.0
    mid = (local_hour(dusk) + length_h / 2.0) % 24.0
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
    days without mains; a longer cut resets it."""
    drift_ppm: float = 3.0
    trust_budget_s: float = 300.0
    holdover_days: float = 7.0
    synced: bool = False
    utc_at_sync: Optional[datetime] = None
    mono_at_sync: float = 0.0
    age_before_mono_s: float = 0.0   # drift accumulated across reboots

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
        if not self.synced:
            return
        if outage_s > self.holdover_days * 86400.0:
            self.reset()
            return
        elapsed = (mono_at_cut - self.mono_at_sync) + outage_s
        self.utc_at_sync = self.utc_at_sync + timedelta(seconds=elapsed)
        self.age_before_mono_s += elapsed
        self.mono_at_sync = 0.0

    def reset(self) -> None:
        self.synced = False
        self.utc_at_sync = None
        self.mono_at_sync = 0.0
        self.age_before_mono_s = 0.0


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
