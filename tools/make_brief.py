"""Build the DC decision brief (docs/brief.html) from the models.

    python tools/make_brief.py            # about 30 s

Every number on the page comes from vdl7.annual, vdl7.skyglow and
vdl7.pilot run on data/dc; the page itself only rescales them (price,
emission factor, streetlight share, curfew compliance) in the browser.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from vdl7.annual import _walk_boost, dc_fleet, expected_level, run_year  # noqa: E402
from vdl7.demand import POLE_SPACING_M, WALK_SPEED_MPS  # noqa: E402
from vdl7.pilot import load_segments, stepped_wedge  # noqa: E402
from vdl7.profiles import DEFAULT_PROFILES, PHASE_ORDER, phase_for_hour  # noqa: E402
from vdl7.schedule import program  # noqa: E402
from vdl7.skyglow import (CLASSES, MOMENTS, NATURAL_CD, PLACES_DC, SKY_STRATEGIES, lighting_for, load_grid,  # noqa: E402
                          plan_retrofits, streetlight_luminance)

TEMPLATE = os.path.join(os.path.dirname(__file__), "brief", "template.html")
OUT = os.path.join(ROOT, "docs", "brief.html")
HEAD_END = "<!-- end head"     # the template's title, meta, font link and styles sit above this marker
SKELETON = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            '<style>:root{color-scheme:light}body{margin:0;font:14px system-ui}img{max-width:100%}'
            '[hidden]{display:none!important}</style>\n{head}</head><body>\n{page}</body></html>\n')
SEED = "ILLUSTRATIVE DRAW - the real seed is published before the draw"


def data() -> dict:
    fleet = dc_fleet()
    years = {}
    for floor in (40, 50, 60):
        r = run_year(fleet, unsensed_floor=floor)
        years[str(floor)] = {k: {kk: v[kk] for kk in ("mwh", "energy_vs_today", "light_vs_today", "skyglow_vs_today",
                                                       "mwh_by_month", "mean_level_pct", "mwh_by_class")}
                             for k, v in r["strategies"].items()}
    out = {"year": {"burn_hours": r["burn_hours"], "fleet_kw": r["fleet"]["kw"], "poles": r["fleet"]["poles"],
                    "by_floor": years}}
    walk = _walk_boost(POLE_SPACING_M / WALK_SPEED_MPS)
    hours = [18 + i * 0.25 for i in range(13 * 4 + 1)]
    night = {}
    for c in CLASSES:
        prof = DEFAULT_PROFILES[c]
        rows = {"phase0": [], "phase1": []}
        for h in hours:
            hh = h % 24
            base = float(prof.levels[PHASE_ORDER.index(phase_for_hour(hh))])
            rows["phase0"].append(round(expected_level(prof, base, hh, "schedule", 50.0, walk), 1))
            rows["phase1"].append(round(expected_level(prof, base, hh, "adaptive", 50.0, walk), 1))
        night[c.value] = {"levels": list(prof.levels), "floor": prof.floor, "cap": prof.boost_cap,
                          "program": [s.__dict__ for s in program(prof, 50.0)], **rows}
    out["night"] = {"hours": hours, "classes": night}
    cells = load_grid()
    cct = {c: fleet.classes[c].mix() for c in CLASSES}
    out["sky"] = {"natural_mcd": NATURAL_CD * 1000, "places": [
        {"key": p.key, "name": p.name, "lat": p.lat, "lon": p.lon,
         "moments": {m: {s: streetlight_luminance(cells, p, lighting_for(s, h, cct)) * 1000 for s in SKY_STRATEGIES}
                     for m, h in MOMENTS.items()}} for p in PLACES_DC]}
    out["retrofits"] = [{"lat": s.lat, "lon": s.lon, "kw": s.globes_kw, "best": max(s.gain, key=s.gain.get),
                         "gain": round(max(s.gain.values()), 4)}
                        for s in plan_retrofits(cells, PLACES_DC, lighting_for("phase1", 1.5, cct), top=8)]
    segs = load_segments()
    plan = stepped_wedge(segs, SEED)
    out["pilot"] = {"segments": len(segs), "waves": [
        {"wave": w, "segments": sum(1 for s in segs if plan.assignment[s.id] == w),
         "lights": sum(s.lights for s in segs if plan.assignment[s.id] == w),
         "start": plan.wave_start(w).isoformat(),
         "wards": sorted({s.ward for s in segs if plan.assignment[s.id] == w})} for w in range(1, plan.waves + 1)]}
    with open(os.path.join(ROOT, "data", "dc", "fleet.json")) as f:
        fl = json.load(f)
    out["fleet"] = {"active": fl["active"], "led": fl["lighttype"]["LED"], "registered": fl["smart_node_registered"],
                    "retrieved": fl["retrieved"], "shield": fl["shield"],
                    "classes": {k: {"poles": v["poles"], "kw": v["trimmed_kw"], "cct": v["cct"], "optics": v["optics"]}
                                for k, v in fl["classes"].items()}}
    return out


def render(template: str, payload: dict) -> str:
    """The template's head part (above the HEAD_END marker line) goes in <head>, the rest in <body>."""
    k = template.find(HEAD_END)
    if k < 0:
        raise ValueError(f"template has no {HEAD_END!r} marker")
    nl = template.find("\n", k)
    head, body = template[:k], template[nl + 1:] if nl >= 0 else ""
    body = body.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    return SKELETON.replace("{head}", head).replace("{page}", body)


def main() -> int:
    with open(TEMPLATE) as f:
        template = f.read()
    page = render(template, data())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(page)
    print("wrote", os.path.relpath(OUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
