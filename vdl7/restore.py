"""Choose complete source interventions against receptor-specific sky budgets.

An exact, bounded multiple-choice search. Contributions and intervention effects
are supplied evidence/assumptions, not discovered facts. No hardware commands.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from decimal import Decimal
from pathlib import Path

MAX_PORTFOLIOS = 1_000_000
EPS = 1e-9


def number(value, name, low=0, high=math.inf):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: expected a number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: expected a finite number in [{low}, {high}]")
    return float(value)


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: expected nonempty text")
    return value


def fields(value, required, name):
    if not isinstance(value, dict) or set(value) != set(required.split()):
        raise ValueError(f"{name}: expected fields {required}")


def indexed(values, name):
    if not isinstance(values, list) or not values:
        raise ValueError(f"{name}: expected a nonempty list")
    out = {}
    for value in values:
        if not isinstance(value, dict):
            raise ValueError(f"{name}: each item must be an object")
        key = text(value.get("id"), f"{name}.id")
        if key in out:
            raise ValueError(f"{name}: duplicate id {key!r}")
        out[key] = value
    return out


def cents(value, name):
    number(value, name)
    amount = Decimal(str(value)) * 100
    if amount != amount.to_integral_value():
        raise ValueError(f"{name}: use no more than two decimal places")
    return int(amount)


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def read_project(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)


def validate(project):
    fields(project, "schema_version title synthetic evidence budget_usd receptors sources scenarios", "project")
    if type(project["schema_version"]) is not int or project["schema_version"] != 1:
        raise ValueError("schema_version must be 1")
    text(project["title"], "title")
    text(project["evidence"], "evidence")
    if type(project["synthetic"]) is not bool:
        raise ValueError("synthetic must be true or false")
    cents(project["budget_usd"], "budget_usd")
    receptors = indexed(project["receptors"], "receptors")
    sources = indexed(project["sources"], "sources")
    scenarios = indexed(project["scenarios"], "scenarios")
    for rid, r in receptors.items():
        fields(r, "id label target_mcd_m2", f"receptor {rid}")
        text(r["label"], "receptor.label")
        number(r["target_mcd_m2"], "target_mcd_m2")
    for sid, s in sources.items():
        fields(s, "id label owner authorized minimum_service_fraction options", f"source {sid}")
        text(s["label"], "source.label")
        text(s["owner"], "source.owner")
        if type(s["authorized"]) is not bool:
            raise ValueError(f"{sid}: authorized must be true or false")
        number(s["minimum_service_fraction"], "minimum_service_fraction", high=1)
        for oid, o in indexed(s["options"], f"{sid}.options").items():
            fields(o, "id label cost_usd service_fraction reviewed remaining_fraction evidence", f"option {oid}")
            if oid == "keep":
                raise ValueError("option id 'keep' is reserved for the unchanged baseline")
            text(o["label"], "option.label")
            text(o["evidence"], "option.evidence")
            cents(o["cost_usd"], "cost_usd")
            number(o["service_fraction"], "service_fraction", high=1)
            if type(o["reviewed"]) is not bool:
                raise ValueError(f"{oid}: reviewed must be true or false")
            if not isinstance(o["remaining_fraction"], dict) or set(o["remaining_fraction"]) != set(scenarios):
                raise ValueError(f"{oid}: remaining_fraction must name every scenario exactly")
            for fraction in o["remaining_fraction"].values():
                number(fraction, "remaining_fraction", high=1)
    for scid, sc in scenarios.items():
        fields(sc, "id label unmanaged_mcd_m2 contributions_mcd_m2", f"scenario {scid}")
        text(sc["label"], "scenario.label")
        if not isinstance(sc["contributions_mcd_m2"], dict) or set(sc["contributions_mcd_m2"]) != set(sources):
            raise ValueError(f"{scid}: contributions must name every source exactly")
        for name, row in [("unmanaged", sc["unmanaged_mcd_m2"]), *sc["contributions_mcd_m2"].items()]:
            if not isinstance(row, dict) or set(row) != set(receptors):
                raise ValueError(f"{scid}/{name}: contributions must name every receptor exactly")
            for value in row.values():
                number(value, "contribution_mcd_m2")
    return receptors, sources, scenarios


def solve(project, budget_usd=None):
    """Cheapest feasible portfolio, else best minimum target completion.

Every scenario/receptor must meet its target; a citywide average cannot hide
one failed place. Options for one source are mutually exclusive complete
packages. 'keep' is always available, including for unconsenting owners.
"""
    receptors, sources, scenarios = validate(project)
    budget = cents(project["budget_usd"] if budget_usd is None else budget_usd, "budget_usd")
    axes = [(scid, rid) for scid in sorted(scenarios) for rid in sorted(receptors)]
    targets = [receptors[rid]["target_mcd_m2"] for _, rid in axes]
    unmanaged = [scenarios[scid]["unmanaged_mcd_m2"][rid] for scid, rid in axes]
    baseline = unmanaged[:]
    floor = unmanaged[:]
    groups, excluded = [], []
    for sid in sorted(sources):
        s = sources[sid]
        contribution = [scenarios[scid]["contributions_mcd_m2"][sid][rid] for scid, rid in axes]
        baseline = [a + b for a, b in zip(baseline, contribution)]
        choices = [{"source": sid, "option": "keep", "label": "Keep current operation", "cost_cents": 0,
                    "remaining": contribution, "evidence": "Unchanged baseline"}]
        for o in sorted(s["options"], key=lambda x: x["id"]):
            reasons = []
            if not s["authorized"]:
                reasons.append("owner authorization missing")
            if not o["reviewed"]:
                reasons.append("service review missing")
            if o["service_fraction"] < s["minimum_service_fraction"]:
                reasons.append("below declared service floor")
            if reasons:
                excluded.append({"source": sid, "option": o["id"], "reasons": reasons})
                continue
            choices.append({"source": sid, "option": o["id"], "label": o["label"],
                            "cost_cents": cents(o["cost_usd"], "cost_usd"), "evidence": o["evidence"],
                            "remaining": [c * o["remaining_fraction"][scid] for c, (scid, _) in zip(contribution, axes)]})
        floor = [v + min(o["remaining"][i] for o in choices) for i, v in enumerate(floor)]
        # Drop strictly dominated options after eligibility, retaining stable IDs on exact ties.
        choices = [o for o in choices if not any(
            p is not o and p["cost_cents"] <= o["cost_cents"]
            and all(a <= b for a, b in zip(p["remaining"], o["remaining"]))
            and (p["cost_cents"] < o["cost_cents"] or p["remaining"] != o["remaining"] or p["option"] < o["option"])
            for p in choices)]
        groups.append(choices)
    combinations = math.prod(len(g) for g in groups)
    if combinations > MAX_PORTFOLIOS:
        raise ValueError(f"{combinations:,} portfolios exceeds exact-search limit {MAX_PORTFOLIOS:,}; "
                         "combine sources into reviewed packages or reduce alternatives; no approximate result was produced")
    best, best_key, count, cheapest_feasible = None, None, 0, None
    for portfolio in itertools.product(*groups):
        cost = sum(o["cost_cents"] for o in portfolio)
        remaining = [unmanaged[i] + sum(o["remaining"][i] for o in portfolio) for i in range(len(axes))]
        feasible = all(v <= t + EPS for v, t in zip(remaining, targets))
        if feasible:
            cheapest_feasible = cost if cheapest_feasible is None else min(cost, cheapest_feasible)
        if cost > budget:
            continue
        count += 1
        progress = min(1.0 if b <= t + EPS else max(0.0, min(1.0, (b - v) / (b - t)))
                       for b, v, t in zip(baseline, remaining, targets))
        key = (0 if feasible else 1, cost if feasible else -progress, sum(remaining), cost,
               tuple(o["option"] for o in portfolio))
        if best_key is None or key < best_key:
            best_key = key
            best = (portfolio, cost, remaining, feasible, progress)
    portfolio, cost, remaining, feasible, progress = best
    rows = [{"scenario": scid, "receptor": rid, "label": receptors[rid]["label"],
             "baseline_mcd_m2": baseline[i], "remaining_mcd_m2": remaining[i], "target_mcd_m2": targets[i],
             "gap_mcd_m2": max(0.0, remaining[i] - targets[i]),
             "reduction_fraction": (baseline[i] - remaining[i]) / baseline[i] if baseline[i] else 0.0,
             "optimistic_floor_without_budget_mcd_m2": floor[i], "meets_target": remaining[i] <= targets[i] + EPS}
            for i, (scid, rid) in enumerate(axes)]
    canonical = json.dumps(project, sort_keys=True, separators=(",", ":"), allow_nan=False)
    status = "feasible" if feasible else "budget_shortfall" if cheapest_feasible is not None else "outside_available_actions"
    return {"schema_version": 1, "title": project["title"], "synthetic": project["synthetic"],
            "project_sha256": hashlib.sha256(canonical.encode()).hexdigest(), "status": status,
            "solver": "exact enumeration after dominance pruning", "candidate_portfolios": combinations,
            "portfolios_within_budget": count, "budget_usd": budget / 100, "cost_usd": cost / 100,
            "minimum_feasible_cost_usd": None if cheapest_feasible is None else cheapest_feasible / 100,
            "worst_target_completion": progress, "receptors": rows, "excluded_options": excluded,
            "actions": [{"source": o["source"], "source_label": sources[o["source"]]["label"],
                         "owner": sources[o["source"]]["owner"], "option": o["option"], "label": o["label"],
                         "cost_usd": o["cost_cents"] / 100, "evidence": o["evidence"]}
                        for o in portfolio if o["option"] != "keep"],
            "limits": ["Planning result only. No commands are sent to lights.",
                       "Every result is conditional on the supplied contributions and complete action packages.",
                       "Scenarios are stress cases, not statistical confidence intervals.",
                       "Service fractions and review flags are declarations, not a photometric safety certification.",
                       "Artificial zenith luminance is not a measure of glare, window trespass, or habitat illuminance.",
                       "Unmanaged light remains in every portfolio; no energy savings or star counts are inferred."]}


def format_plan(result):
    lines = [result["title"], "SYNTHETIC EXAMPLE — not a DC forecast" if result["synthetic"] else "CONDITIONAL MODEL — not a measured outcome",
             f"Status: {result['status']}", f"Selected cost: ${result['cost_usd']:,.2f} / ${result['budget_usd']:,.2f}"]
    minimum = result["minimum_feasible_cost_usd"]
    lines.append("No available portfolio meets every target." if minimum is None else f"Least cost to meet every target: ${minimum:,.2f}")
    for action in result["actions"]:
        lines.append(f"  {action['owner']}: {action['label']} (${action['cost_usd']:,.2f})")
    for row in result["receptors"]:
        lines.append(f"  {row['scenario']}/{row['receptor']}: {row['baseline_mcd_m2']:.3f} -> "
                     f"{row['remaining_mcd_m2']:.3f} mcd/m²; target {row['target_mcd_m2']:.3f}; "
                     f"{'met' if row['meets_target'] else 'NOT MET'}")
    lines.append("Use `nocturne experiment` to preregister a source trial; then measure and re-plan.")
    return "\n".join(lines)
