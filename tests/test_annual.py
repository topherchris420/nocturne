"""The business case: a year of nights for a whole fleet.

`EXT-BIZ-*` calibrate the expected-value year against the 400-node network
simulation, then check the year's shape and the strategies' ordering.
"""
from __future__ import annotations

import json
import os

import pytest

from vdl7.annual import (CLASSES, Economics, dc_fleet, expected_level, format_report, run_year, spec_fleet,
                         _walk_boost)
from vdl7.profiles import DEFAULT_PROFILES, Phase, RoadClass
from vdl7.sites import site

ROOT = os.path.join(os.path.dirname(__file__), "..")


@pytest.fixture(scope="module")
def dc_year():
    return run_year(dc_fleet())


def test_EXT_BIZ_1_one_night_matches_the_network_simulation():
    """The 13 October night with the Section 6.4 fleet against the 400-node
    simulation's committed results. The simulation's photocells switch on at
    about -1.7 deg and off at -0.8 deg, about 20 minutes more burn than the
    -3 deg window used here, which is why its energy ratio sits up to two
    points higher; the spectral and optical steps agree to a point."""
    with open(os.path.join(ROOT, "out", "summary.json")) as f:
        sim = json.load(f)["scenarios"]
    r = run_year(spec_fleet(), days=("2026-10-13", "2026-10-13"), walk_step_s=30.0)["strategies"]
    assert sim["dimming"]["energy_vs_today"] - 0.03 <= r["phase1"]["energy_vs_today"] <= sim["dimming"]["energy_vs_today"]
    assert r["phase1_u0"]["skyglow_vs_today"] == pytest.approx(sim["dimming_u0"]["skyglow_index"], abs=0.01)
    assert r["phase2_warm"]["skyglow_vs_today"] == pytest.approx(sim["nocturne"]["skyglow_index"], abs=0.01)


def test_EXT_BIZ_2_the_year_has_the_right_shape(dc_year):
    r = dc_year
    assert 4050 <= r["burn_hours"] <= 4250                 # dusk-to-dawn at 38.9 N
    months = r["strategies"]["today"]["mwh_by_month"]
    assert max(months) in (months[0], months[11]) and min(months) == months[5]
    assert r["fleet"]["poles"] > 70_000 and 3900 < r["fleet"]["kw"] < 4200
    today = r["strategies"]["today"]
    assert today["mwh"] == pytest.approx(r["fleet"]["kw"] * r["burn_hours"] / 1000.0, rel=1e-3)


def test_EXT_BIZ_3_strategies_order_as_they_should(dc_year):
    st = dc_year["strategies"]
    assert st["today"]["mwh"] > st["phase0"]["mwh"] > st["phase1"]["mwh"]
    assert st["phase1_u0"]["mwh"] == st["phase1"]["mwh"]                         # optics change no watts
    assert st["phase1_u0"]["skyglow_vs_today"] < st["phase1"]["skyglow_vs_today"]
    assert st["phase2_warm"]["mwh"] > st["phase1"]["mwh"]                         # warm costs efficacy...
    assert st["phase2_warm"]["skyglow_vs_today"] < st["phase1_u0"]["skyglow_vs_today"]   # ...and buys sky
    for k in ("phase0", "phase1", "phase1_u0"):
        assert st[k]["light_vs_today"] == pytest.approx(st[k]["energy_vs_today"], abs=1e-4)
    assert st["phase0"]["saved_usd"] == pytest.approx(st["phase0"]["saved_mwh"] * 130, rel=1e-3)


def test_EXT_BIZ_4_streets_without_sensors_never_drop_below_the_unsensed_floor():
    for road in (RoadClass.LOCAL, RoadClass.ALLEY, RoadClass.PARK):
        prof = DEFAULT_PROFILES[road]
        for h in (19.0, 22.5, 23.5, 2.0, 5.5):
            assert expected_level(prof, prof.base(Phase.DEEP), h, "schedule", 50.0, _walk_boost(21.4)) >= 50.0
    lo = run_year(dc_fleet(), days=("2027-01-10", "2027-01-16"), unsensed_floor=40.0)["strategies"]["phase0"]
    hi = run_year(dc_fleet(), days=("2027-01-10", "2027-01-16"), unsensed_floor=60.0)["strategies"]["phase0"]
    assert lo["saved_mwh"] > hi["saved_mwh"] > 0


def test_EXT_BIZ_5_adaptive_uplift_comes_from_people_and_traffic():
    """At 02:00 an arterial runs above its 50 % base because of the loop
    volume; a local street sits a little above 30 % because of walkers."""
    art, loc = DEFAULT_PROFILES[RoadClass.ARTERIAL], DEFAULT_PROFILES[RoadClass.LOCAL]
    w = _walk_boost(21.4)
    assert 50 < expected_level(art, 50, 2.0, "adaptive", 50, w) < 60
    assert 30 < expected_level(loc, 30, 2.0, "adaptive", 50, w) < 32
    assert expected_level(loc, 80, 19.0, "adaptive", 50, w) == 80          # evening above the cap: no change


def test_EXT_BIZ_6_runs_for_any_city_including_polar_ones():
    """Tromso's two months of polar night are outweighed by the midnight sun
    and the long light twilights, so its year has fewer hours of real night
    than DC's."""
    for key, lo_h, hi_h in [("tromso", 3500, 4100), ("honolulu", 3900, 4400), ("sydney", 4000, 4400)]:
        r = run_year(spec_fleet(10_000), site=site(key), days=("2027-01-01", "2027-12-31"), step_s=900)
        assert lo_h <= r["burn_hours"] <= hi_h, (key, r["burn_hours"])
        assert r["strategies"]["phase1"]["energy_vs_today"] < 0.8


def test_EXT_BIZ_7_report_and_break_even(dc_year):
    text = format_report(dc_year)
    assert "Phase 0 pays back" in text and "Washington, DC" in text
    be = dc_year["break_even"]
    assert be["phase0_integration_usd"] == pytest.approx(3 * dc_year["strategies"]["phase0"]["saved_usd"], rel=1e-6)
    cheap = run_year(dc_fleet(), econ=Economics(usd_per_kwh=0.065), days=("2027-03-01", "2027-03-07"))
    assert cheap["strategies"]["phase0"]["saved_usd"] < run_year(
        dc_fleet(), days=("2027-03-01", "2027-03-07"))["strategies"]["phase0"]["saved_usd"]
    assert set(dc_year["strategies"]["phase1"]["mean_level_pct"]) == {c.value for c in CLASSES}
