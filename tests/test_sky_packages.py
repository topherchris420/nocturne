"""The technology packages behind docs/TECHNOLOGY.md (tools/sky_packages.py).

`EXT-PKG-*` check that the packages agree with `nocturne sky` where they
overlap, that every lever darkens the sky only when it acts (a curfew only
after 23:00, shielding at every hour), that the non-street levers outweigh
the streetlights after midnight under the Tucson prior, and the Milky Way
threshold.
"""
from __future__ import annotations

import importlib.util
import os

import pytest

from vdl7.annual import dc_fleet
from vdl7.skyglow import CLASSES, NATURAL_CD, PLACES_DC, load_grid, msas_from_cd, sky_scenarios

ROOT = os.path.join(os.path.dirname(__file__), "..")
_spec = importlib.util.spec_from_file_location("sky_packages", os.path.join(ROOT, "tools", "sky_packages.py"))
pk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pk)


@pytest.fixture(scope="module")
def rows():
    return pk.packages()


def _row(rows, place, moment):
    return next(r for r in rows if r["place"] == place and r["moment"] == moment)


def test_EXT_PKG_1_today_and_the_streetlight_programme_match_nocturne_sky(rows):
    fleet = dc_fleet()
    cct = {c: fleet.classes[c].mix() for c in CLASSES}
    ref = sky_scenarios(load_grid(), PLACES_DC, cct, other_curfew_cut=0.5)
    for r in ref:
        mine = _row(rows, r["place"], r["moment"])["sky"]
        assert mine["today"]["msas"] == r["sky"]["today"]["msas"]
        assert mine["streetlights"]["msas"] == r["sky"]["nocturne"]["msas"]
        assert mine["streetlights + curfew 50 %"]["msas"] == r["sky"]["nocturne_plus_signal"]["msas"]


def test_EXT_PKG_2_each_lever_acts_only_when_it_should(rows):
    for r in rows:
        s = {k: v["msas"] for k, v in r["sky"].items()}
        assert s["streetlights"] >= s["today"] and s["shielding"] > s["today"]
        assert s["all three"] >= max(v for k, v in s.items() if k != "all three")
        if r["moment"] == "evening":                       # 21:00: before the curfew
            assert s["curfew 30 %"] == s["curfew 50 %"] == s["today"]
        else:
            assert s["today"] < s["curfew 30 %"] < s["curfew 50 %"]
            assert s["curfew 50 %"] == s["shielding"]       # half the other light, by either route


def test_EXT_PKG_3_after_midnight_the_other_lighting_is_the_bigger_lever(rows):
    """Under the Tucson prior, the MLO's minimum 30 % curfew on the rest of
    the city's lighting does more for every place than Nocturne's whole
    streetlight programme."""
    for p in PLACES_DC:
        s = _row(rows, p.key, "after_midnight")["sky"]
        assert s["curfew 30 %"]["msas"] > s["streetlights"]["msas"]
        assert s["all three"]["stars"] > 2 * s["today"]["stars"]


def test_EXT_PKG_4_milky_way_threshold():
    assert pk.MILKY_WAY_ARTIFICIAL_CD / NATURAL_CD == pytest.approx(688 / 174)
    assert msas_from_cd(pk.MILKY_WAY_ARTIFICIAL_CD + NATURAL_CD) == pytest.approx(20.3, abs=0.05)
    assert pk.milky_way_cut(0.0) == 0.0 and pk.milky_way_cut(pk.MILKY_WAY_ARTIFICIAL_CD / 2) == 0.0
    assert pk.milky_way_cut(10 * pk.MILKY_WAY_ARTIFICIAL_CD) == pytest.approx(0.9)


def test_EXT_PKG_5_a_darker_prior_needs_a_smaller_cut_and_inputs_are_checked():
    lo = {r["place"]: r["milky_way_cut"] for r in pk.packages(share=0.10, places=PLACES_DC[:2])}
    hi = {r["place"]: r["milky_way_cut"] for r in pk.packages(share=0.20, places=PLACES_DC[:2])}
    assert all(0.8 < hi[k] < lo[k] < 1.0 for k in lo)
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            pk.packages(share=bad, places=PLACES_DC[:1])
    with pytest.raises(ValueError):
        pk.packages(places=PLACES_DC[:1], packages={"x": ("today", 1.2, 0.0)})
    assert pk.main(["--share", "0"]) == 2
