"""Fetch DC's streetlight inventory from DC GIS and reduce it to what Nocturne
needs: the fleet by Nocturne road class, and a ~550 m grid of where the light
is, for the business case and the skyglow model.

    python tools/fetch_dc_inventory.py                 # writes data/dc/fleet.json, data/dc/grid.csv
    python tools/fetch_dc_inventory.py --raw raw.jsonl # also keep every record

Source: DDOT / DC GIS, "Streetlight" layer of the DDOT/Streetlights map
service. Only aggregates are committed; re-run this to refresh them.

Class mapping (documented in data/dc/README.md):
  Alley Light                         -> alley
  Bike Trail Light                    -> park (trail / river edge)
  everything else, by ROADCLASSIFICATION:
    Principal / Minor Arterial        -> arterial
    Interstate / Freeway              -> arterial, flagged `freeway` (state-DOT
                                         style lighting; dimmed only by the arterial profile)
    Collector                         -> collector
    Local, unknown                    -> local
Tunnel/underpass, overhead guide-sign, navigation and tower lights are kept
static (`excluded`): tunnels need adaptation lighting by day and the others
are not street lighting.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date

LAYER = "https://maps2.dcgis.dc.gov/dcgis/rest/services/DDOT/Streetlights/MapServer/0"
FIELDS = ["OBJECTID", "ASSETSTATUS", "ASSETTYPE", "LIGHTTYPE", "WATTAGE1", "WATTAGE2", "NUMBERLIGHTS",
          "CCT", "FIXTURESTYLE", "ROADCLASSIFICATION", "WARD", "SHIELD", "POLEHEIGHT",
          "CLIGHT_SCAN_SUCCESS_1", "CLIGHT_DIMMING_1", "LANDUSE", "OWNER"]
PAGE = 1000
CELL_DEG_LAT = 0.005                       # ~556 m
CELL_DEG_LON = 0.0064                      # ~555 m at 38.9 N

ASSET_ALLEY, ASSET_TRAIL = 2, 10
ASSET_EXCLUDED = {3: "overhead guide sign", 4: "tunnel/underpass", 6: "navigation", 8: "tower"}
ROAD = {14: "arterial", 16: "arterial", 11: "arterial", 12: "arterial", 17: "collector", 19: "local"}
FREEWAY = {11, 12}
LIGHTTYPE = {6: "LED", 1: "HPS", 3: "INC", 4: "MV", 5: "MH", 7: "FL"}


def _get(params: dict, retries: int = 4) -> dict:
    url = LAYER + "/query?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                d = json.loads(r.read())
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception:                               # network blips: back off and retry
            if attempt == retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_all(progress=True):
    """Every record, paged by OBJECTID so the result does not depend on
    server-side pagination support."""
    last, out = -1, []
    while True:
        d = _get({"where": f"OBJECTID > {last}", "outFields": ",".join(FIELDS), "orderByFields": "OBJECTID",
                  "resultRecordCount": PAGE, "outSR": 4326, "f": "json"})
        feats = d.get("features", [])
        if not feats:
            break
        for f in feats:
            a = dict(f["attributes"])
            g = f.get("geometry") or {}
            a["x"], a["y"] = g.get("x"), g.get("y")
            out.append(a)
        last = feats[-1]["attributes"]["OBJECTID"]
        if progress:
            print(f"\r{len(out):6d} records", end="", file=sys.stderr, flush=True)
    if progress:
        print(file=sys.stderr)
    return out


def _num(s) -> float:
    """'49', '30W', '67%' -> float; anything else -> 0."""
    m = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)\s*[wW%]?\s*$", str(s if s is not None else ""))
    return float(m.group(1)) if m else 0.0


def pole_watts(a: dict) -> float:
    """Rated watts on the pole. WATTAGE1 is the first luminaire; WATTAGE2, if
    set, every further one; otherwise all luminaires are WATTAGE1."""
    n = max(1, int(a.get("NUMBERLIGHTS") or 1))
    w1, w2 = _num(a.get("WATTAGE1")), _num(a.get("WATTAGE2"))
    return w1 + (w2 if w2 > 0 else w1) * (n - 1)


def trim(a: dict) -> float:
    """Commissioned maximum output (CLIGHT_DIMMING_1), 0-1. Missing means 100 %."""
    v = _num(a.get("CLIGHT_DIMMING_1"))
    return v / 100.0 if 0 < v <= 100 else 1.0


def cct_of(a: dict) -> str:
    s = str(a.get("CCT") or "").strip().lower()
    if s.endswith("k") and s[:-1].isdigit():
        s = str(int(s[:-1]) * 100)
    if s.isdigit():
        v = int(s)
        for ref in (1500, 2200, 2700, 3000, 4000, 5000):
            if abs(v - ref) <= 60:
                return f"{ref}K"
        return f"{v}K"
    return "unknown"


def classify(a: dict):
    """(nocturne class or None if excluded, flags)."""
    at = a.get("ASSETTYPE")
    if at in ASSET_EXCLUDED:
        return None, {"excluded": ASSET_EXCLUDED[at]}
    if at == ASSET_ALLEY:
        return "alley", {}
    if at == ASSET_TRAIL:
        return "park", {}
    rc = a.get("ROADCLASSIFICATION")
    return ROAD.get(rc, "local"), ({"freeway": True} if rc in FREEWAY else {})


def reduce(records):
    active = [a for a in records if a.get("ASSETSTATUS") == "Active"]
    fleet = {"classes": defaultdict(lambda: Counter()), "cct": defaultdict(Counter), "ward": defaultdict(Counter),
             "lighttype": Counter(), "excluded": Counter(), "shield": Counter(), "fixture": Counter(),
             "registered": Counter(), "trim_hist": Counter(), "freeway": 0,
             "landuse": defaultdict(Counter), "not_led": Counter()}
    grid = defaultdict(lambda: defaultdict(float))
    for a in active:
        cls, flags = classify(a)
        w, t = pole_watts(a), trim(a)
        fleet["lighttype"][LIGHTTYPE.get(a.get("LIGHTTYPE"), "unknown")] += 1
        if cls is None:
            fleet["excluded"][flags["excluded"]] += 1
            continue
        if flags.get("freeway"):
            fleet["freeway"] += 1
        c = fleet["classes"][cls]
        c["poles"] += 1
        c["luminaires"] += max(1, int(a.get("NUMBERLIGHTS") or 1))
        c["rated_w"] += w
        c["trimmed_w"] += w * t
        fleet["cct"][cls][cct_of(a)] += 1
        fleet["landuse"][cls][str(a.get("LANDUSE") or "unknown")] += 1
        if a.get("LIGHTTYPE") != 6:
            fleet["not_led"][cls] += 1
        fleet["ward"][str(a.get("WARD") or "unknown")][cls] += 1
        fleet["shield"][str(a.get("SHIELD") or "unknown")] += 1
        fleet["fixture"][str(a.get("FIXTURESTYLE") or "unknown")] += 1
        fleet["registered"]["yes" if a.get("CLIGHT_SCAN_SUCCESS_1") == "Successful Registration" else "no"] += 1
        fleet["trim_hist"][int(round(t * 10)) * 10] += 1
        x, y = a.get("x"), a.get("y")
        if x is None or y is None:
            continue
        key = (math.floor(y / CELL_DEG_LAT), math.floor(x / CELL_DEG_LON))
        cell = grid[key]
        cell[f"{cls}_n"] += 1
        cell[f"{cls}_w"] += w * t
        cell["sx"] += x
        cell["sy"] += y
        cell["n"] += 1
    return active, fleet, grid


def write(fleet, grid, n_records, n_active, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    classes = ["arterial", "collector", "local", "alley", "park"]
    total = sum(fleet["classes"][c]["poles"] for c in classes)
    doc = {
        "source": "DDOT / DC GIS, Streetlights map service, layer 0 'Streetlight'",
        "url": LAYER,
        "retrieved": date.today().isoformat(),
        "records": n_records,
        "active": n_active,
        "lighttype": dict(fleet["lighttype"].most_common()),
        "excluded_static": dict(fleet["excluded"]),
        "freeway_poles_in_arterial": fleet["freeway"],
        "classes": {c: {"poles": int(fleet["classes"][c]["poles"]),
                        "luminaires": int(fleet["classes"][c]["luminaires"]),
                        "share": round(fleet["classes"][c]["poles"] / total, 4),
                        "rated_kw": round(fleet["classes"][c]["rated_w"] / 1000.0, 1),
                        "trimmed_kw": round(fleet["classes"][c]["trimmed_w"] / 1000.0, 1),
                        "mean_rated_w": round(fleet["classes"][c]["rated_w"] / max(1, fleet["classes"][c]["poles"]), 1),
                        "mean_trim": round(fleet["classes"][c]["trimmed_w"] / max(1e-9, fleet["classes"][c]["rated_w"]), 3),
                        "cct": dict(fleet["cct"][c].most_common()),
                        "landuse": dict(fleet["landuse"][c].most_common()),
                        "not_led": int(fleet["not_led"][c])}
                    for c in classes},
        "by_ward": {w: dict(v) for w, v in sorted(fleet["ward"].items())},
        "shield": dict(fleet["shield"].most_common()),
        "fixture_style_code": dict(fleet["fixture"].most_common(12)),
        "smart_node_registered": dict(fleet["registered"]),
        "commissioned_trim_pct_hist": {str(k): v for k, v in sorted(fleet["trim_hist"].items())},
        "grid": {"cell_deg_lat": CELL_DEG_LAT, "cell_deg_lon": CELL_DEG_LON, "cells": len(grid)},
    }
    with open(os.path.join(out_dir, "fleet.json"), "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    cols = ["lat", "lon"] + [f"{c}_{k}" for c in classes for k in ("n", "w")]
    with open(os.path.join(out_dir, "grid.csv"), "w") as f:
        f.write(",".join(cols) + "\n")
        for key in sorted(grid):
            cell = grid[key]
            lat, lon = cell["sy"] / cell["n"], cell["sx"] / cell["n"]   # centroid of the poles in the cell
            row = [f"{lat:.5f}", f"{lon:.5f}"] + [f"{cell.get(f'{c}_{k}', 0.0):.0f}" for c in classes for k in ("n", "w")]
            f.write(",".join(row) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data", "dc"))
    ap.add_argument("--raw", help="also write every fetched record as JSON lines here")
    ap.add_argument("--from-raw", help="reduce a previously saved --raw file instead of fetching")
    a = ap.parse_args(argv)
    if a.from_raw:
        with open(a.from_raw) as f:
            records = [json.loads(line) for line in f]
    else:
        records = fetch_all()
    if a.raw:
        with open(a.raw, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
    active, fleet, grid = reduce(records)
    write(fleet, grid, len(records), len(active), a.out)
    print(f"{len(records)} records, {len(active)} active, {len(grid)} grid cells -> {os.path.abspath(a.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
