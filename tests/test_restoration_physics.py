"""Schema 2: directional effects, uncertain coefficients and interacting
sources, checked against an independent brute-force oracle."""
import copy
import itertools
import random

import pytest

from tools.restoration_demo import district
from vdl7.restore import ProjectError, check, solve


def tiny(**extra):
    """Two sources, two places, one scenario: small enough to reason about by hand."""
    project = {"schema_version": 2, "title": "Tiny", "synthetic": True, "evidence": "test fixture", "budget_usd": 1000,
               "receptors": [{"id": "near", "label": "Near", "target_mcd_m2": 1.0},
                             {"id": "far", "label": "Far", "target_mcd_m2": 1.0}],
               "sources": [
                   {"id": "street", "label": "Street", "owner": "city", "authorized": True, "minimum_service_fraction": 0,
                    "options": [{"id": "shield", "label": "Shield", "cost_usd": 100, "service_fraction": 1, "reviewed": True,
                                 "remaining_fraction": {"s": 0.5}, "evidence": "test"}]},
                   {"id": "sign", "label": "Sign", "owner": "shop", "authorized": True, "minimum_service_fraction": 0,
                    "options": [{"id": "off", "label": "Off", "cost_usd": 300, "service_fraction": 0, "reviewed": True,
                                 "remaining_fraction": {"s": 0}, "evidence": "test"}]}],
               "scenarios": [{"id": "s", "label": "S", "unmanaged_mcd_m2": {"near": 0.2, "far": 0.2},
                              "contributions_mcd_m2": {"street": {"near": 1.0, "far": 1.0},
                                                       "sign": {"near": 0.3, "far": 0.3}}}]}
    project.update(extra)
    return project


def test_directional_fraction_changes_the_decision():
    project = tiny()
    assert solve(project)["actions"][0]["option"] == "shield"          # 0.2 + 0.5 + 0.3 = 1.0 at both places
    # Shielding redirects light: it darkens the far place but brightens the near one.
    project["sources"][0]["options"][0]["remaining_fraction"]["s"] = {"near": 1.2, "far": 0.1}
    result = solve(project)
    assert result["status"] == "outside_available_actions"
    project["receptors"][0]["target_mcd_m2"] = 1.4
    result = solve(project)
    # The shield alone would leave 0.2 + 1.2 + 0.3 = 1.7 at the near place: the sign must go too.
    assert result["status"] == "feasible" and [a["option"] for a in result["actions"]] == ["off", "shield"]
    rows = {r["receptor"]: r for r in result["receptors"]}
    assert rows["near"]["remaining_mcd_m2"] == pytest.approx(0.2 + 1.2)
    assert rows["far"]["remaining_mcd_m2"] == pytest.approx(0.2 + 0.1)


def test_ranges_are_planned_at_their_pessimistic_end():
    project = tiny()
    project["scenarios"][0]["contributions_mcd_m2"]["street"]["near"] = [0.8, 1.0, 1.4]
    result = solve(project)
    # Shield alone: 0.2 + 0.7 + 0.3 = 1.2 > 1 at the pessimistic end, so the sign must go too.
    assert result["status"] == "feasible" and result["cost_usd"] == 400
    near = next(r for r in result["receptors"] if r["receptor"] == "near")
    assert near["remaining_range_mcd_m2"] == pytest.approx([0.2 + 0.4, 0.2 + 0.7])
    assert near["target_status"] == "met"
    u = result["uncertainty"]
    assert u["ranged_values"] == 1
    assert u["central_plan"]["cost_usd"] == 100 and u["cost_of_uncertainty_usd"] == 300


def test_a_target_met_only_at_the_optimistic_end_is_reported_as_uncertain():
    project = tiny(budget_usd=100)
    project["scenarios"][0]["contributions_mcd_m2"]["street"]["near"] = [0.8, 1.4]
    result = solve(project)
    assert result["status"] == "budget_shortfall"
    near = next(r for r in result["receptors"] if r["receptor"] == "near")
    assert near["target_status"] == "uncertain" and not near["meets_target"]


def test_synergy_makes_a_pair_worth_more_than_its_parts():
    project = tiny()
    for r in project["receptors"]:
        r["target_mcd_m2"] = 0.55
    assert solve(project)["status"] == "outside_available_actions"            # additive best: 0.2 + 0.5 + 0 = 0.7
    project["interactions"] = [{"id": "shared-wall", "label": "Sign lit the wall the shield now darkens",
                                "when": {"street": "shield", "sign": "off"}, "delta_mcd_m2": {"s": -0.2},
                                "evidence": "test"}]
    result = solve(project)
    assert result["status"] == "feasible" and result["cost_usd"] == 400
    assert result["interactions"][0]["active"]


def test_rebound_is_charged_to_the_plan_that_causes_it():
    project = tiny()
    project["interactions"] = [{"id": "rebound", "label": "Owners add floodlights when the street dims",
                                "when": {"street": "shield"}, "delta_mcd_m2": {"s": {"near": 0.25, "far": 0}},
                                "evidence": "test"}]
    result = solve(project)
    assert result["cost_usd"] == 400                                        # the shield alone no longer suffices
    near = next(r for r in result["receptors"] if r["receptor"] == "near")
    assert near["remaining_mcd_m2"] == pytest.approx(0.2 + 0.5 + 0 + 0.25)


def test_an_interaction_cannot_remove_more_light_than_exists():
    project = tiny()
    project["interactions"] = [{"id": "too-good", "label": "Impossible", "when": {"sign": "off"},
                                "delta_mcd_m2": {"s": -5}, "evidence": "test"}]
    with pytest.raises(ProjectError, match="remove more light than the sources emit"):
        solve(project)


def test_version_one_refuses_version_two_features():
    project = district()
    project["scenarios"][0]["unmanaged_mcd_m2"]["park"] = [0.2, 0.4]
    project["sources"][0]["options"][0]["remaining_fraction"]["clear"] = {"park": .7, "neighborhood": .7, "river": .7}
    with pytest.raises(ProjectError) as e:
        solve(project)
    messages = " | ".join(m for _, m in e.value.problems)
    assert "ranges need schema_version 2" in messages and "per observation point need schema_version 2" in messages


def test_every_problem_is_reported_with_its_path():
    project = district()
    project["budgte_usd"] = project.pop("budget_usd")
    project["sources"][2]["options"][0]["remaining_fraction"]["hazy"] = 1.5
    project["sources"][3]["options"][0]["cost_usd"] = "250"
    with pytest.raises(ProjectError) as e:
        solve(project)
    paths = dict(e.value.problems)
    assert "did you mean 'budget_usd'" in paths["project"] or any("did you mean" in m for _, m in e.value.problems)
    assert "sources[offices].options[blinds].remaining_fraction.hazy" in paths
    assert "sources[signs].options[curfew].cost_usd" in paths
    assert len(e.value.problems) >= 4


def test_check_explains_what_no_source_can_fix():
    project = tiny()
    project["scenarios"][0]["unmanaged_mcd_m2"]["far"] = 1.5
    report = check(project)
    assert report["ok"]
    assert any("unmanaged light alone" in w["message"] and "far" in w["path"] for w in report["warnings"])
    bad = check({"schema_version": 3})
    assert not bad["ok"] and any(p["path"] == "schema_version" for p in bad["problems"])


def oracle(project):
    """Independent brute force: every eligible combination, pessimistic values, no pruning."""
    hi = lambda v: v[-1] if isinstance(v, list) else v
    receptors = {r["id"]: r["target_mcd_m2"] for r in project["receptors"]}
    scenarios = {s["id"]: s for s in project["scenarios"]}

    def fraction(option, scid, rid):
        f = option["remaining_fraction"][scid]
        return hi(f[rid] if isinstance(f, dict) else f)

    menus = []
    for s in project["sources"]:
        menu = [("keep", 0, None)]
        for o in s["options"]:
            if s["authorized"] and o["reviewed"] and o["service_fraction"] >= s["minimum_service_fraction"]:
                menu.append((o["id"], o["cost_usd"], o))
        menus.append([(s["id"], *m) for m in menu])
    best = None
    for combo in itertools.product(*menus):
        chosen = {sid: oid for sid, oid, _, _ in combo}
        ok = True
        for scid, sc in scenarios.items():
            for rid, target in receptors.items():
                total = hi(sc["unmanaged_mcd_m2"][rid])
                for sid, oid, _, option in combo:
                    c = hi(sc["contributions_mcd_m2"][sid][rid])
                    total += c if option is None else c * fraction(option, scid, rid)
                for k in project.get("interactions", []):
                    if all(chosen[sid] in (w if isinstance(w, list) else [w]) for sid, w in k["when"].items()):
                        d = k["delta_mcd_m2"][scid]
                        total += hi(d[rid] if isinstance(d, dict) else d)
                ok = ok and total <= target + 1e-9
        cost = sum(c for _, _, c, _ in combo)
        if ok and (best is None or cost < best):
            best = cost
    return best


def random_project(rng):
    rids, scids = ["a", "b"], ["x", "y"]
    project = {"schema_version": 2, "title": "Random", "synthetic": True, "evidence": "test", "budget_usd": 0,
               "receptors": [{"id": r, "label": r, "target_mcd_m2": round(rng.uniform(0.6, 2.0), 2)} for r in rids],
               "sources": [], "scenarios": [], "interactions": []}

    def maybe_range(v):
        return [round(v * 0.8, 3), round(v * 1.25, 3)] if rng.random() < 0.3 else round(v, 3)

    for i in range(4):
        options = []
        for j in range(rng.randint(1, 3)):
            fr = {s: ({r: maybe_range(rng.uniform(0, 1.2)) for r in rids} if rng.random() < 0.4 else maybe_range(rng.uniform(0, 1)))
                  for s in scids}
            options.append({"id": f"o{j}", "label": "o", "cost_usd": rng.randint(0, 9) * 10, "service_fraction": 1,
                            "reviewed": rng.random() > 0.1, "remaining_fraction": fr, "evidence": "test"})
        project["sources"].append({"id": f"s{i}", "label": "s", "owner": "o", "authorized": rng.random() > 0.1,
                                   "minimum_service_fraction": 0, "options": options})
    for s in scids:
        project["scenarios"].append({"id": s, "label": s, "unmanaged_mcd_m2": {r: maybe_range(rng.uniform(0, .3)) for r in rids},
                                     "contributions_mcd_m2": {f"s{i}": {r: maybe_range(rng.uniform(0, .6)) for r in rids}
                                                              for i in range(4)}})
    for k in range(rng.randint(0, 2)):
        a, b = rng.sample(range(4), 2)
        when = {f"s{a}": rng.choice(["keep"] + [o["id"] for o in project["sources"][a]["options"]]),
                f"s{b}": [o["id"] for o in project["sources"][b]["options"]]}
        project["interactions"].append({"id": f"k{k}", "label": "k", "when": when, "evidence": "test",
                                        "delta_mcd_m2": {s: round(rng.uniform(-0.05, 0.3), 3) for s in scids}})
    return project


def test_exact_search_matches_brute_force_with_ranges_directions_and_interactions():
    rng = random.Random(20261015)
    checked = 0
    for _ in range(150):
        project = random_project(rng)
        expected = oracle(project)
        for budget in (0, 60, 10_000):
            result = solve(project, budget_usd=budget)
            assert result["minimum_feasible_cost_usd"] == expected
            if expected is not None and expected <= budget:
                assert result["status"] == "feasible" and result["cost_usd"] == expected
            else:
                assert result["status"] != "feasible"
            checked += 1
    assert checked == 450


def test_reordering_inputs_with_interactions_changes_nothing():
    project = random_project(random.Random(7))
    project["budget_usd"] = 10_000
    original = solve(project)
    shuffled = copy.deepcopy(project)
    for key in ("sources", "receptors", "scenarios", "interactions"):
        shuffled[key].reverse()
    for s in shuffled["sources"]:
        s["options"].reverse()
    again = solve(shuffled)
    assert again["actions"] == original["actions"] and again["receptors"] == original["receptors"]
