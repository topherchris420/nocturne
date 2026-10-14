"""Measurement and verification from sky-quality-meter logs.

`EXT-OBS-*` check the Moon against JPL-grade ephemerides (PyEphem values at
the 2026 eclipses and a lunar month in October), the log formats, the
filters, and that the curfew-step estimator recovers an effect planted in a
synthetic station's year of readings, clouds, Moon and all.
"""
from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from vdl7.clock import DC_LAT, DC_LON, POSIX_TZ, local_hour, solar_elevation_exact
from vdl7.observe import (curfew_steps, dark, difference, moon, read_sqm, steady, verify, write_ida)

UTC = timezone.utc

# PyEphem 4.1.6, topocentric at the White House, no refraction.
EPHEM = [("2026-08-12T17:46", 65.31, 198.62, 0.000),     # total solar eclipse (Spain, Iceland)
         ("2026-03-03T11:33", 0.42, 277.13, 1.000),      # total lunar eclipse
         ("2026-10-14T03:00", -33.62, 262.33, 0.120),
         ("2026-10-20T01:00", 30.59, 193.22, 0.631),
         ("2026-10-26T04:00", 65.28, 152.88, 0.998)]


@pytest.mark.parametrize("t, alt, az, lit", EPHEM)
def test_EXT_OBS_1_moon_matches_ephemerides(t, alt, az, lit):
    m = moon(datetime.fromisoformat(t).replace(tzinfo=UTC), DC_LAT, DC_LON)
    assert m.alt_deg == pytest.approx(alt, abs=0.5)
    assert m.az_deg == pytest.approx(az, abs=1.0)
    assert m.illuminated == pytest.approx(lit, abs=0.01)


def test_EXT_OBS_2_eclipses_are_where_the_sun_and_moon_line_up():
    new = moon(datetime(2026, 8, 12, 17, 46, tzinfo=UTC), DC_LAT, DC_LON)
    full = moon(datetime(2026, 3, 3, 11, 33, tzinfo=UTC), DC_LAT, DC_LON)
    assert new.elongation_deg < 1.5 and full.elongation_deg > 178.5


def test_EXT_OBS_3_log_formats(tmp_path):
    t0 = datetime(2026, 11, 3, 4, 0, tzinfo=UTC)
    rs = [(t0 + timedelta(minutes=5 * i), 18.0 + 0.01 * i) for i in range(10)]
    p = tmp_path / "ida.dat"
    write_ida(rs, str(p))
    assert read_sqm(str(p)) == [(t, pytest.approx(m)) for t, m in rs]
    c = tmp_path / "plain.csv"
    c.write_text("UTC,MSAS,temp\n" + "\n".join(f"{t.isoformat()},{m},4" for t, m in rs) + "\nbad,row,x\n")
    assert len(read_sqm(str(c))) == 10
    z = tmp_path / "zulu.csv"
    z.write_text("timestamp,mpsas\n2026-11-03T04:00:00Z,18.5\n")
    assert read_sqm(str(z)) == [(t0, 18.5)]
    with pytest.raises(ValueError):
        (tmp_path / "x.csv").write_text("when,what\n1,2\n")
        read_sqm(str(tmp_path / "x.csv"))


def test_EXT_OBS_4_filters_drop_twilight_moonlight_and_clouds():
    t0 = datetime(2026, 10, 18, 22, 0, tzinfo=UTC)          # 18:00 EDT; a half-lit Moon sets after midnight
    rs = [(t0 + timedelta(minutes=10 * i), 18.0) for i in range(60)]
    kept = dark(rs, DC_LAT, DC_LON)
    assert kept and all(solar_elevation_exact(DC_LAT, DC_LON, t) < -18 for t, _ in kept)
    assert all(moon(t, DC_LAT, DC_LON).alt_deg < -5 for t, _ in kept)
    assert len(kept) < len(rs) / 2 and kept[0][0] > t0 + timedelta(hours=5)
    full = datetime(2026, 10, 25, 22, 0, tzinfo=UTC)          # full Moon up all night: nothing usable
    assert dark([(full + timedelta(minutes=10 * i), 18.0) for i in range(60)], DC_LAT, DC_LON) == []
    noisy = [(t, 18.0 + (0.4 if i % 2 else 0.0)) for i, (t, _) in enumerate(rs)]
    assert steady(noisy) == [] and len(steady(rs)) == len(rs) - 4
    assert curfew_steps([(t + timedelta(hours=4), m) for t, m in noisy]) == {}


def _station(effect: float, seed: int = 4, go_live: date = date(2026, 11, 1)):
    """Sep-Dec 2026 at 5-min cadence: a sky that darkens slowly through the
    evening, a 0.03 mag step the city already had at 23:00, nightly aerosol
    swings, 25 % cloudy nights and real moonlight; after `go_live` the
    curfew step grows by `effect`."""
    rng = random.Random(seed)
    out = []
    day = date(2026, 9, 1)
    while day < date(2026, 12, 20):
        offset = rng.gauss(0.0, 0.15)
        cloudy = rng.random() < 0.25
        t = datetime(day.year, day.month, day.day, 23, 0, tzinfo=UTC)     # ~19:00 local
        for i in range(12 * 10):
            tt = t + timedelta(minutes=5 * i)
            h = local_hour(tt, POSIX_TZ)
            hrs = (h - 21.0) % 24.0 if h >= 12 or h < 6 else 0.0
            m = 17.8 + offset + 0.06 * hrs + (0.03 if (h >= 23 or h < 6) else 0.0)
            if day >= go_live and (h >= 23 or h < 6):
                m += effect
            if cloudy:
                m = 16.8 + rng.gauss(0.0, 0.25)
            mo = moon(tt, DC_LAT, DC_LON)
            if mo.alt_deg > 0:
                m -= 1.5 * mo.illuminated * math.sin(math.radians(mo.alt_deg))
            out.append((tt, m + rng.gauss(0.0, 0.02)))
        day += timedelta(days=1)
    return out


def test_EXT_OBS_5_curfew_step_recovers_a_planted_effect():
    r = verify(_station(0.12), date(2026, 11, 1), DC_LAT, DC_LON)
    est = r["curfew_step_change"]
    assert est.lo < 0.12 < est.hi and abs(est.effect - 0.12) < 0.03
    assert est.n_before >= 10 and est.n_after >= 10
    assert r["dark"] < r["readings"] / 2                     # twilight and Moon removed...
    assert r["nights_with_step"] < 0.85 * len({t.date() for t, _ in _station(0.0)})   # ...and cloudy nights


def test_EXT_OBS_6_no_effect_means_an_interval_around_zero():
    est = verify(_station(0.0, seed=9), date(2026, 11, 1), DC_LAT, DC_LON)["curfew_step_change"]
    assert est.lo < 0.0 < est.hi and abs(est.effect) < 0.03
    with pytest.raises(ValueError):
        difference({date(2026, 1, 1): 0.1}, {date(2026, 2, 1): 0.2})


def test_EXT_OBS_7_curfew_steps_pair_readings_from_the_same_evening():
    t0 = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)            # 22:00 EST
    rs = [(t0 + timedelta(minutes=5 * i), 18.0 if i < 12 else 18.2) for i in range(24)]
    steps = curfew_steps(rs)
    assert list(steps) == [date(2026, 11, 9)] and steps[date(2026, 11, 9)] == pytest.approx(0.2)
