"""Skyglow at named places.

`EXT-SKY-*` check the scattering kernel against closed-form near-field
limits, the unit conversions, DC's grid against its fleet, and the
direction of every effect the brief relies on.
"""
from __future__ import annotations

import json
import math
import os

import pytest

from vdl7.profiles import RoadClass
from vdl7.skyglow import (CLASSES, NATURAL_CD, PLACES_DC, Atmosphere, Lighting, SkyAt, calibrate, cd_from_msas,
                          kernel, lighting_for, load_grid, msas_from_cd, nelm, plan_retrofits, sky_scenarios,
                          stars_visible, streetlight_luminance)

ROOT = os.path.join(os.path.dirname(__file__), "..")
CCT = {RoadClass.ARTERIAL: "3000K", RoadClass.COLLECTOR: "2700K", RoadClass.LOCAL: "2700K",
       RoadClass.ALLEY: "2700K", RoadClass.PARK: "2700K"}


@pytest.fixture(scope="module")
def cells():
    return load_grid()


def test_EXT_SKY_1_units_limiting_magnitude_and_stars():
    assert NATURAL_CD == pytest.approx(1.71e-4, rel=0.01)                 # 22.0 mag/arcsec^2
    assert msas_from_cd(cd_from_msas(18.3)) == pytest.approx(18.3)
    assert nelm(22.0) == pytest.approx(6.6, abs=0.1) and nelm(18.0) == pytest.approx(4.0, abs=0.1)
    assert stars_visible(6.0) == 2400 and stars_visible(4.0) < stars_visible(4.5) < stars_visible(5.0)
    assert all(nelm(m) < nelm(m + 0.5) for m in (16.0, 17.0, 18.0, 19.0, 20.0, 21.0))


def test_EXT_SKY_2_kernel_matches_the_closed_form_near_field():
    """Single Rayleigh scattering in a uniform, aerosol-free atmosphere has
    closed forms near the source: 5 b / (16 pi^2 d) for Lambertian emission
    and 9 b / (128 pi d) for uniform upward emission. (The real 8 km scale
    height trims about 1 % even at 10 m: the integrand's tail falls only as
    1/z^2, so the top of the atmosphere shows up logarithmically.)"""
    b = 0.0973 / 8000.0
    atm = Atmosphere(aod_550=1e-9, rayleigh_h_m=1e7, rayleigh_tau_550=b * 1e7)
    for d in (10.0, 20.0):
        assert kernel(d, "lambert", "R", atm) == pytest.approx(5 * b / (16 * math.pi ** 2 * d), rel=0.01)
        assert kernel(d, "iso", "R", atm) == pytest.approx(9 * b / (128 * math.pi * d), rel=0.01)


def test_EXT_SKY_3_kernel_shape_near_and_far():
    for emission in ("lambert", "iso"):
        for sc in ("R", "A"):
            near = math.log(kernel(60, emission, sc) / kernel(30, emission, sc)) / math.log(2)
            far = math.log(kernel(40000, emission, sc) / kernel(20000, emission, sc)) / math.log(2)
            assert -1.15 < near < -0.95 and far < -2.5, (emission, sc, near, far)
    # aerosol is the near-city scatterer; molecules carry light farther
    assert kernel(300, "lambert", "A") / kernel(300, "lambert", "R") > kernel(30000, "lambert", "A") / kernel(30000, "lambert", "R")
    dusty = Atmosphere(aod_550=0.30)
    assert 1.6 < kernel(100, "lambert", "A", dusty) / kernel(100, "lambert", "A") < 2.0


def test_EXT_SKY_4_grid_carries_the_whole_fleet(cells):
    with open(os.path.join(ROOT, "data", "dc", "fleet.json")) as f:
        fleet = json.load(f)
    for c in CLASSES:
        kw = sum(cell.kw[c] for cell in cells)
        assert kw == pytest.approx(fleet["classes"][c.value]["trimmed_kw"], rel=0.01), c
    assert 0.2 < sum(cell.globe_kw for cell in cells) / sum(cell.total_kw for cell in cells) < 0.35


def test_EXT_SKY_5_every_lever_darkens_the_sky_in_the_right_proportion(cells):
    mall, park = PLACES_DC[-1], PLACES_DC[0]
    full = Lighting({c: 100.0 for c in CLASSES}, CCT)
    half = Lighting({c: 50.0 for c in CLASSES}, CCT)
    u0 = Lighting({c: 100.0 for c in CLASSES}, CCT, globes_u0=True)
    warm = Lighting({c: 100.0 for c in CLASSES}, {c: "2200K" for c in CLASSES})
    base = streetlight_luminance(cells, park, full)
    assert streetlight_luminance(cells, park, half) == pytest.approx(base / 2, rel=1e-9)
    assert streetlight_luminance(cells, park, u0) < base
    assert streetlight_luminance(cells, park, warm) < base
    eye = streetlight_luminance(cells, park, warm, eye="scotopic") / streetlight_luminance(cells, park, full, eye="scotopic")
    assert eye < streetlight_luminance(cells, park, warm) / base                 # the dark-adapted eye gains more
    assert streetlight_luminance(cells, mall, full) > base                        # downtown is brighter


def test_EXT_SKY_6_calibration_from_a_measurement():
    model = 1e-3
    other = calibrate(model, 18.0)
    assert other == pytest.approx(cd_from_msas(18.0) - NATURAL_CD - model)
    assert calibrate(0.05, 18.0) == 0.0                                          # model too bright: no negative light
    sky = SkyAt("x", model, other)
    assert sky.msas == pytest.approx(18.0) and 0 < sky.streetlight_share < 1


def test_EXT_SKY_7_streetlights_alone_cannot_fix_the_sky_but_a_shared_curfew_can(cells):
    """The brief's central claim, as an assertion: after midnight Nocturne
    removes most of the streetlights' share of the sky at every place, which
    moves the whole sky by about a tenth of a magnitude when streetlights
    are 15 % of the artificial light; the rest of the city halving its light
    after curfew roughly doubles the stars."""
    rows = [r for r in sky_scenarios(cells, PLACES_DC[:2], CCT) if r["moment"] == "after_midnight"]
    for r in rows:
        assert r["streetlight_reduction"]["phase2_warm"] > 0.5
        sky = r["sky"]
        assert 0.05 < sky["nocturne"]["msas"] - sky["today"]["msas"] < 0.2
        assert sky["nocturne_plus_signal"]["stars"] > 1.8 * sky["today"]["stars"]
    measured = sky_scenarios(cells, PLACES_DC[:1], CCT, measured={"rock-creek": 18.6})
    assert measured[0]["other_source"] == "measured" and measured[0]["sky"]["today"]["msas"] == pytest.approx(18.6, abs=0.01)


def test_EXT_SKY_8_globe_retrofits_are_ranked_where_they_help_the_places(cells):
    light = lighting_for("phase1", 1.5, CCT)
    only_park = {p.key: 0.0 for p in PLACES_DC}
    only_park["rock-creek"] = 1.0
    steps = plan_retrofits(cells, PLACES_DC, light, weights=only_park, top=5)
    park = PLACES_DC[0]
    from vdl7.skyglow import distance_m
    assert distance_m(park.lat, park.lon, steps[0].lat, steps[0].lon) < 4000
    assert [s.score for s in steps] == sorted((s.score for s in steps), reverse=True)
    assert all(0 < s.gain["rock-creek"] < 1 and s.globes_kw >= 0.5 for s in steps)
