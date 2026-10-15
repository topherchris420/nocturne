"""Rebuild the invented districts and end-to-end source-attribution example.

Run from any directory: python tools/restoration_demo.py --out /tmp/nocturne-demo
Every luminance, position, lumen, cost, permission, service review and
observation is synthetic.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vdl7.attribution import COLUMNS, analyze, make_trial
from vdl7.derive import derive
from vdl7.restore import solve
from vdl7.restoration_report import render
from vdl7.skyglow import msas_from_cd


def district():
    def option(key, label, cost, clear, haze, service=1, reviewed=True):
        return {"id": key, "label": label, "cost_usd": cost, "service_fraction": service,
                "reviewed": reviewed, "remaining_fraction": {"clear": clear, "hazy": haze},
                "evidence": "INVENTED demonstration coefficient and cost; replace with local measurements and review."}

    def source(key, label, owner, floor, options, authorized=True):
        return {"id": key, "label": label, "owner": owner, "authorized": authorized,
                "minimum_service_fraction": floor, "options": options}

    sources = [
        source("streets", "Residential streets", "Example transport department", 0.6, [
            option("schedule", "Reviewed late-night schedule", 800, .70, .75, .6),
            option("shield-and-schedule", "Shielding plus reviewed schedule", 2400, .40, .50, .8)]),
        source("facades", "Decorative building facades", "Example building consortium", 0, [
            option("closing-time", "Switch decorative uplights off after closing", 500, .12, .16, 0)]),
        source("offices", "Office windows", "Example office cooperative", 1, [
            option("blinds", "Close blinds while preserving indoor task light", 1800, .25, .35),
            option("blinds-and-zoning", "Blinds plus vacancy zoning", 2200, .15, .20),
            option("all-off", "Switch all interior lighting off", 100, .05, .05, 0)]),
        source("signs", "Commercial signs", "Example merchants association", 0, [
            option("curfew", "Apply the shared curfew to nonessential signs", 250, .05, .07, 0)]),
        source("sports", "Sports field spill", "Example recreation department", 0, [
            option("booking", "Tie field lights to bookings and shutdown checks", 1200, .10, .12, 0),
            option("optics", "Replace floodlight optics", 4000, .40, .35)]),
        source("crossing", "Pedestrian crossing", "Example transport department", .9, [
            option("dim", "Deep-dim the crossing", 100, .2, .2, .2),
            option("shield", "Shield crossing while retaining task illumination", 2000, .70, .65)]),
        source("monument", "Neighboring monument", "Nonparticipating owner", 0, [
            option("curfew", "Request a monument-lighting curfew", 600, .05, .05, 0)], authorized=False),
    ]
    receptor_ids = ["park", "neighborhood", "river"]
    baseline = {"streets": [.30, .40, .28], "facades": [.85, .40, .35], "offices": [.25, .85, .15],
                "signs": [.40, .65, .35], "sports": [.60, .25, .65], "crossing": [.10, .10, .08], "monument": [.25, .20, .10]}
    scenarios = []
    for key, label, factor, background in [("clear", "Clear reference sky", 1, [.3, .35, .4]),
                                            ("hazy", "Hazy stress case", 1.4, [.4, .45, .55])]:
        scenarios.append({"id": key, "label": label, "unmanaged_mcd_m2": dict(zip(receptor_ids, background)),
                          "contributions_mcd_m2": {s: {r: round(v * factor, 6) for r, v in zip(receptor_ids, values)}
                                                   for s, values in baseline.items()}})
    return {"schema_version": 1, "title": "An invented district: restore the sky without dimming every task",
            "synthetic": True, "evidence": "SYNTHETIC. No DC observations, quotations, owner approvals or engineering reviews are represented.",
            "budget_usd": 8000, "receptors": [{"id": r, "label": label, "target_mcd_m2": target} for r, label, target in
                zip(receptor_ids, ["Park observation point", "Neighborhood observation point", "River observation point"], [1.55, 1.7, 1.6])],
            "sources": sources, "scenarios": scenarios}


def physical_district():
    """The same kind of district described physically: emitters with positions,
    lumens in the assessed window, uplight and reflectance, options as physical
    changes, and three conditions including haze and snow. `nocturne derive`
    turns it into contributions and per-place remaining fractions."""
    def option(key, label, cost, change, service=1, reviewed=True):
        return {"id": key, "label": label, "cost_usd": cost, "service_fraction": service, "reviewed": reviewed,
                "change": change, "evidence": "INVENTED cost and physical change; replace with photometry, quotations and review."}

    def source(key, label, owner, floor, spectrum, emitters, options, authorized=True):
        return {"id": key, "label": label, "owner": owner, "authorized": authorized, "minimum_service_fraction": floor,
                "spectrum": spectrum, "emitters": emitters, "options": options}

    def emitter(x, y, lumens, uplight, reflectance, radius):
        return {"x_m": x, "y_m": y, "radius_m": radius, "lumens": lumens, "uplight_fraction": uplight,
                "reflectance": reflectance}

    sources = [
        source("streets", "Residential streets", "Example transport department", 0.6, "3000K",
               [emitter(-800, 300, 4.0e6, 0.04, 0.12, 600), emitter(700, -200, 4.0e6, 0.04, 0.12, 600),
                emitter(0, 900, 3.0e6, 0.04, 0.12, 600)], [
                   option("schedule", "Reviewed late-night schedule", 800, {"output_factor": 0.6}, 0.6),
                   option("shield-and-schedule", "Top shields on globes plus reviewed schedule", 2400,
                          {"output_factor": 0.6, "uplight_fraction": 0.0}, 0.8)]),
        source("facades", "Decorative building facades", "Example building consortium", 0, "3000K",
               [emitter(-300, 200, 1.5e6, 0.35, 0.30, 200)], [
                   option("closing-time", "Switch decorative uplights off after closing", 500, {"output_factor": 0.1}, 0)]),
        source("offices", "Office windows", "Example office cooperative", 1, "4000K",
               [emitter(200, 100, 2.0e6, 0.15, 0.10, 250)], [
                   option("blinds", "Close blinds while preserving indoor task light", 1800, {"output_factor": 0.3}),
                   option("blinds-and-zoning", "Blinds plus vacancy zoning", 2200, {"output_factor": 0.18}),
                   option("all-off", "Switch all interior lighting off", 100, {"output_factor": 0.05}, 0)]),
        source("signs", "Commercial signs", "Example merchants association", 0, "4000K",
               [emitter(100, -300, 0.8e6, 0.40, 0.10, 200)], [
                   option("curfew", "Apply the shared curfew to nonessential signs", 250, {"output_factor": 0.05}, 0)]),
        source("sports", "Sports field floodlights", "Example recreation department", 0, "4000K",
               [emitter(1500, -900, 3.0e6, 0.10, 0.25, 120)], [
                   option("booking", "Tie field lights to bookings and shutdown checks", 1200, {"output_factor": 0.1}, 0),
                   option("optics", "Replace floodlight optics (full cutoff, same field lighting)", 4000, {"uplight_fraction": 0.01})]),
        source("crossing", "Pedestrian crossing", "Example transport department", 0.9, "3000K",
               [emitter(-100, 0, 0.1e6, 0.05, 0.15, 30)], [
                   option("dim", "Deep-dim the crossing", 100, {"output_factor": 0.2}, 0.2),
                   option("shield", "Shield crossing while retaining task illumination", 2000, {"uplight_fraction": 0.0})]),
        source("monument", "Neighboring monument", "Nonparticipating owner", 0, "3000K",
               [emitter(-2500, 1500, 2.0e6, 0.50, 0.40, 100)], [
                   option("curfew", "Request a monument-lighting curfew", 600, {"output_factor": 0.05}, 0)], authorized=False),
    ]
    return {"schema": "nocturne-physical/1", "title": "An invented district, derived from geometry and atmosphere",
            "synthetic": True,
            "evidence": "SYNTHETIC. Emitter positions, lumens, uplight, reflectance, costs, rebound and atmospheres are invented.",
            "budget_usd": 8000, "coordinates": "local_m", "calibration_factor": [0.8, 1.0, 1.25],
            "receptors": [{"id": "park", "label": "Park observation point", "target_mcd_m2": 1.8, "x_m": -1600, "y_m": 900},
                          {"id": "neighborhood", "label": "Neighborhood observation point", "target_mcd_m2": 3.6, "x_m": 0, "y_m": 0},
                          {"id": "river", "label": "River observation point", "target_mcd_m2": 1.5, "x_m": 2200, "y_m": -1500}],
            "conditions": [
                {"id": "clear", "label": "Clear night (AOD 0.10)", "aod_550": 0.10,
                 "unmanaged_mcd_m2": {"park": 0.30, "neighborhood": 0.35, "river": 0.40}},
                {"id": "hazy", "label": "Hazy night (AOD 0.45)", "aod_550": 0.45,
                 "unmanaged_mcd_m2": {"park": 0.40, "neighborhood": 0.45, "river": 0.55}},
                {"id": "snow", "label": "Snow cover (AOD 0.12, surfaces reflect 3.5x)", "aod_550": 0.12,
                 "reflectance_multiplier": 3.5, "unmanaged_mcd_m2": {"park": 0.55, "neighborhood": 0.65, "river": 0.70}}],
            "sources": sources,
            "interactions": [{"id": "sign-rebound", "label": "Merchants leave security floodlights on after the sign curfew",
                              "when": {"signs": "curfew"},
                              "delta_mcd_m2": {"clear": {"park": 0, "neighborhood": 0.05, "river": 0},
                                               "hazy": {"park": 0, "neighborhood": [0.05, 0.08], "river": 0},
                                               "snow": {"park": 0, "neighborhood": 0.09, "river": 0}},
                              "evidence": "INVENTED rebound; a source-isolation trial with the floodlights logged would measure it."}]}


def synthetic_readings(trial, path):
    rng = random.Random(23)
    truth = {"facades": .8, "signs": .55}
    with open(path, "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for a in trial["assignments"]:
            drift = rng.uniform(-.15, .15)
            reduction = truth[a["source"]] * (1 - a["requested_fraction"])
            target = 3.2 + drift - reduction + rng.gauss(0, .025)
            control = .8 + drift + rng.gauss(0, .008)
            writer.writerow({"pair_id": a["pair_id"], "period": a["period"], "status": "ok",
                "reason": "SYNTHETIC fixture; no field measurements", "samples": 20,
                "applied_fraction": a["requested_fraction"], "target_msas": f"{msas_from_cd(target / 1000):.8f}",
                "control_msas": f"{msas_from_cd(control / 1000):.8f}"})
    return truth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="new output directory")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    project = district()
    plan = solve(project)
    trial = make_trial(["facades", "signs"], "2027-01-04", "nocturne-synthetic-demo-v1", synthetic=True)
    truth = synthetic_readings(trial, out / "synthetic-readings.csv")
    evidence = analyze(trial, out / "synthetic-readings.csv")
    physical = physical_district()
    derived = derive(physical)
    derived_plan = solve(derived)
    for name, value in [("district", project), ("plan", plan), ("trial", trial), ("attribution", evidence),
                        ("synthetic-truth", {"source_baseline_mcd_m2": truth, "synthetic": True}),
                        ("physical-district", physical), ("derived-district", derived), ("derived-plan", derived_plan)]:
        (out / (name + ".json")).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (out / "report.html").write_text(render(plan), encoding="utf-8")
    (out / "derived-report.html").write_text(render(derived_plan), encoding="utf-8")
    print(json.dumps({"synthetic": True, "out": str(out), "status": plan["status"], "cost_usd": plan["cost_usd"]}))


if __name__ == "__main__":
    main()
