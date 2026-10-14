"""The DC inventory reduction (tools/fetch_dc_inventory.py).

`EXT-INV-*` check, without the network, how single DDOT records are read:
which lights are kept static, what a pole with no wattage is taken to draw,
how CCT labels are read, and that the committed aggregates agree with each
other.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
_spec = importlib.util.spec_from_file_location("fetch_dc_inventory", os.path.join(ROOT, "tools", "fetch_dc_inventory.py"))
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)


def rec(**kw):
    a = {"ASSETSTATUS": "Active", "ASSETTYPE": 1, "ROADCLASSIFICATION": 19, "FIXTURESTYLE": 22,
         "WATTAGE1": "40", "NUMBERLIGHTS": 1, "CCT": "27k", "x": -77.03, "y": 38.9, "STREETSEGMID": 7}
    a.update(kw)
    return a


def test_EXT_INV_1_static_lights_are_not_in_the_dimmed_fleet():
    """Tunnels and the wallpacks under bridge decks need light by day too."""
    assert inv.classify(rec(ASSETTYPE=13)) == (None, {"excluded": "under deck"})
    assert inv.classify(rec(ASSETTYPE=4))[0] is None
    assert inv.classify(rec(ASSETTYPE=2))[0] == "alley" and inv.classify(rec())[0] == "local"
    active, fleet, _grid = inv.reduce([rec(), rec(ASSETTYPE=13, NUMBERLIGHTS=232, WATTAGE1="60")])
    assert fleet["classes"]["local"]["poles"] == 1 and fleet["excluded"]["under deck"] == 1


def test_EXT_INV_2_a_pole_without_a_wattage_draws_its_peers_median():
    peers = [rec(WATTAGE1=str(w)) for w in (30, 40, 40, 50)] * 6
    table = inv.wattage_table(peers + [rec(WATTAGE1=None)])
    assert inv.pole_watts(rec(WATTAGE1=None), table) == 40.0
    assert inv.pole_watts(rec(WATTAGE1=None)) == 0.0                     # without the table: as recorded
    assert inv.pole_watts(rec(WATTAGE1="30", WATTAGE2="20", NUMBERLIGHTS=3), table) == 70.0
    _, fleet, _ = inv.reduce(peers + [rec(WATTAGE1="")])
    assert fleet["imputed_w"]["local"] == 1 and fleet["classes"]["local"]["rated_w"] == sum(
        inv._num(p["WATTAGE1"]) for p in peers) + 40.0


@pytest.mark.parametrize("raw, label", [("27k", "2700K"), ("30K", "3000K"), ("3000K", "3000K"), ("3000", "3000K"),
                                        ("2703", "2700K"), ("N/A", "unknown"), (None, "unknown"), ("1500", "1500K")])
def test_EXT_INV_3_cct_labels(raw, label):
    assert inv.cct_of({"CCT": raw}) == label


def test_EXT_INV_4_committed_aggregates_agree():
    with open(os.path.join(ROOT, "data", "dc", "fleet.json")) as f:
        fleet = json.load(f)
    with open(os.path.join(ROOT, "data", "dc", "segments.csv")) as f:
        segs = list(csv.DictReader(f))
    assert "under deck" in fleet["excluded_static"] and sum(fleet["wattage_imputed_poles"].values()) > 0
    poles = sum(c["poles"] for c in fleet["classes"].values())
    assert sum(int(s["lights"]) for s in segs) <= poles
    assert all((s["lat"] == "") == (s["lon"] == "") for s in segs)
