"""Decision properties and scientific failure modes, without hardware actuation."""
import copy
import csv
import itertools
import json

import pytest

from tools.restoration_demo import district, synthetic_readings
from vdl7.attribution import COLUMNS, _sign_p, analyze, make_trial, validate_trial
from vdl7.cli import main
from vdl7.restore import read_project, solve
from vdl7.restoration_report import render
from vdl7.skyglow import msas_from_cd


def test_example_meets_each_target_and_preserves_exclusions():
    result = solve(district())
    assert result["status"] == "feasible"
    assert result["cost_usd"] == result["minimum_feasible_cost_usd"] == 6550
    assert all(r["meets_target"] for r in result["receptors"])
    selected = {a["source"]: a["option"] for a in result["actions"]}
    assert "crossing" not in selected and "monument" not in selected
    assert selected["offices"] == "blinds-and-zoning"
    assert len({a["source"] for a in result["actions"]}) == len(result["actions"])
    assert len(result["excluded_options"]) == 3


def test_budget_and_control_limits_are_different():
    result = solve(district(), budget_usd=1000)
    assert result["status"] == "budget_shortfall" and result["cost_usd"] <= 1000
    assert result["minimum_feasible_cost_usd"] == 6550
    project = district()
    for r in project["receptors"]:
        r["target_mcd_m2"] = 0.1
    result = solve(project, budget_usd=100000)
    assert result["status"] == "outside_available_actions"
    assert result["minimum_feasible_cost_usd"] is None
    assert all(r["optimistic_floor_without_budget_mcd_m2"] > .1 for r in result["receptors"])


def test_one_bad_place_cannot_be_hidden_by_an_average():
    project = district()
    for r in project["receptors"]:
        r["target_mcd_m2"] = .01 if r["id"] == "river" else 100
    result = solve(project)
    assert result["status"] == "outside_available_actions"
    assert not all(r["meets_target"] for r in result["receptors"])


def test_order_does_not_change_the_selected_actions():
    project = district()
    original = solve(project)
    for key in ("sources", "receptors", "scenarios"):
        project[key].reverse()
    for source in project["sources"]:
        source["options"].reverse()
    reordered = solve(project)
    assert reordered["actions"] == original["actions"]
    assert reordered["receptors"] == original["receptors"]


def test_more_money_never_decreases_worst_target_completion():
    results = [solve(district(), budget_usd=b) for b in (0, 100, 1000, 3000, 6000, 8000)]
    progress = [r["worst_target_completion"] for r in results]
    assert progress == sorted(progress)
    assert results[0]["actions"] == []


def test_search_limit_refuses_to_claim_an_approximate_optimum(monkeypatch):
    import vdl7.restore as restoration
    monkeypatch.setattr(restoration, "MAX_PORTFOLIOS", 1)
    with pytest.raises(ValueError, match="no approximate result"):
        solve(district())


def test_missing_review_is_excluded_and_zero_light_can_meet_zero_target():
    project = district()
    project["sources"][0]["options"][0]["reviewed"] = False
    result = solve(project)
    assert any("service review missing" in a["reasons"] for a in result["excluded_options"])
    for scenario in project["scenarios"]:
        scenario["unmanaged_mcd_m2"] = dict.fromkeys(scenario["unmanaged_mcd_m2"], 0)
        for source in scenario["contributions_mcd_m2"]:
            scenario["contributions_mcd_m2"][source] = dict.fromkeys(scenario["contributions_mcd_m2"][source], 0)
    for receptor in project["receptors"]:
        receptor["target_mcd_m2"] = 0
    result = solve(project, budget_usd=0)
    assert result["status"] == "feasible" and result["cost_usd"] == 0
    assert result["actions"] == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "0.2"])
def test_nonfinite_or_mistyped_inputs_are_refused(bad):
    project = district()
    project["scenarios"][0]["unmanaged_mcd_m2"]["park"] = bad
    with pytest.raises(ValueError):
        solve(project)


def test_missing_scenarios_unknown_keys_and_duplicate_ids_are_errors(tmp_path):
    project = district()
    del project["sources"][0]["options"][0]["remaining_fraction"]["hazy"]
    with pytest.raises(ValueError, match="every scenario"):
        solve(project)
    project = district()
    project["sources"][0]["options"][0]["cost_usd"] = 2.001
    with pytest.raises(ValueError, match="decimal"):
        solve(project)
    project = district()
    project["receptors"].append(copy.deepcopy(project["receptors"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        solve(project)
    path = tmp_path / "bad.json"
    path.write_text('{"budget_usd": 1, "budget_usd": 10000}')
    with pytest.raises(ValueError, match="duplicate"):
        read_project(path)


def test_exact_search_matches_independent_small_knapsack_oracle():
    # Four independent sources, one reviewed action each. Check every budget
    # against an independent subsets oracle, including a case greedy misses.
    project = {"schema_version": 1, "title": "Oracle", "synthetic": True, "evidence": "test fixture",
               "budget_usd": 0, "receptors": [{"id": "r", "label": "R", "target_mcd_m2": 9}],
               "sources": [], "scenarios": [{"id": "s", "label": "S", "unmanaged_mcd_m2": {"r": 1}, "contributions_mcd_m2": {}}]}
    costs, gains = [4, 5, 7, 8], [3, 5, 6, 8]
    for i, (cost, gain) in enumerate(zip(costs, gains)):
        project["sources"].append({"id": str(i), "label": str(i), "owner": "test", "authorized": True,
            "minimum_service_fraction": 0, "options": [{"id": "off", "label": "off", "cost_usd": cost,
            "service_fraction": 0, "reviewed": True, "remaining_fraction": {"s": 0}, "evidence": "test"}]})
        project["scenarios"][0]["contributions_mcd_m2"][str(i)] = {"r": gain}
    for budget in range(25):
        feasible = [sum(c * b for c, b in zip(costs, bits)) for bits in itertools.product((0, 1), repeat=4)
                    if 1 + sum(g * (1 - b) for g, b in zip(gains, bits)) <= 9
                    and sum(c * b for c, b in zip(costs, bits)) <= budget]
        result = solve(project, budget_usd=budget)
        assert (result["status"] == "feasible") == bool(feasible)
        if feasible:
            assert result["cost_usd"] == min(feasible)


def test_html_escapes_untrusted_labels():
    project = district()
    project["title"] = '<script>alert("bad")</script>'
    page = render(solve(project))
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "Synthetic example" in page


def test_trial_is_reproducible_and_one_source_per_night():
    trial = make_trial(["signs", "facades"], "2027-03-12", "published-seed")
    assert trial == make_trial(["facades", "signs"], "2027-03-12", "published-seed")
    nights = {}
    for assignment in trial["assignments"]:
        nights.setdefault(assignment["night"], set()).add(assignment["source"])
        assert assignment["start_utc"] < assignment["end_utc"]
    assert all(len(v) == 1 for v in nights.values())
    for i in range(0, len(trial["assignments"]), 2):
        pair = trial["assignments"][i:i + 2]
        assert {a["condition"] for a in pair} == {"baseline", "dim"}
    trial["assignments"][0]["requested_fraction"] = 0
    with pytest.raises(ValueError, match="fingerprint"):
        validate_trial(trial)


def test_known_sources_are_recovered_in_linear_units(tmp_path):
    trial = make_trial(["facades", "signs"], "2027-01-04", "synthetic-recovery")
    path = tmp_path / "readings.csv"
    truth = synthetic_readings(trial, path)
    result = analyze(trial, path)
    for estimate in result["estimates"]:
        assert estimate["status"] == "reduction_detected"
        assert estimate["source_at_baseline_mcd_m2"] == pytest.approx(truth[estimate["source"]], abs=.05)
        assert estimate["p_bonferroni"] <= .05


def write_constant_response(trial, path, effect=0, shared_drift=.1):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        for a in trial["assignments"]:
            drift = shared_drift * a["period"]
            treatment = effect if a["condition"] == "dim" else 0
            writer.writerow({"pair_id": a["pair_id"], "period": a["period"], "status": "ok", "reason": "test",
                "samples": 10, "applied_fraction": a["requested_fraction"],
                "target_msas": msas_from_cd((3 + drift - treatment) / 1000),
                "control_msas": msas_from_cd((1 + drift) / 1000)})


def test_shared_weather_change_is_not_mistaken_for_source_reduction(tmp_path):
    trial = make_trial(["facades"], "2027-01-04", "weather-null")
    path = tmp_path / "null.csv"
    write_constant_response(trial, path)
    estimate = analyze(trial, path)["estimates"][0]
    assert abs(estimate["removed_mcd_m2"]) < 1e-10
    assert estimate["status"] == "not_resolved" and estimate["p_two_sided"] == 1


def test_negative_effect_is_retained(tmp_path):
    trial = make_trial(["facades"], "2027-01-04", "negative")
    path = tmp_path / "brightening.csv"
    write_constant_response(trial, path, effect=-.2)
    estimate = analyze(trial, path)["estimates"][0]
    assert estimate["removed_mcd_m2"] == pytest.approx(-.2)
    assert estimate["status"] == "unexpected_brightening"


def test_exact_randomization_controls_error_over_all_null_assignments():
    # Under the sharp null, the six night differences are fixed and their
    # treatment labels are independently random. Enumerate the whole design.
    rejected = 0
    for signs in itertools.product((-1, 1), repeat=6):
        values = [s * v for s, v in zip(signs, (1, 2, 3, 4, 5, 6))]
        p, _ = _sign_p(values, "fixed")
        rejected += p <= .05
    assert rejected / 64 <= .05


def test_missing_excluded_and_duplicate_windows_are_accounted_for(tmp_path):
    trial = make_trial(["facades"], "2027-01-04", "missing")
    path = tmp_path / "data.csv"
    write_constant_response(trial, path, effect=.2)
    rows = list(csv.DictReader(path.open()))
    rows[0]["status"], rows[0]["reason"] = "excluded", "clouds"
    rows = rows[:-1]
    def save(values):
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(values)
    save(rows)
    result = analyze(trial, path)
    assert result["estimates"][0]["usable_pairs"] == 10
    assert result["estimates"][0]["status"] == "incomplete_exploratory"
    assert {p["reason"] for p in result["lost_pairs"]} == {"missing period", "excluded period"}
    save(rows + [rows[1]])
    with pytest.raises(ValueError, match="duplicate"):
        analyze(trial, path)
    rows[1]["applied_fraction"] = ".77"
    save(rows)
    with pytest.raises(ValueError, match="differs"):
        analyze(trial, path)


def test_cli_writes_reviewable_outputs_and_returns_unmet_status(tmp_path, capsys):
    project = tmp_path / "project.json"
    project.write_text(json.dumps(district()))
    report = tmp_path / "report.html"
    assert main(["restore", str(project), "--json", "--report", str(report)]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["status"] == "feasible" and report.exists()
    assert main(["restore", str(project), "--budget", "1", "--json"]) == 3
    out, _ = capsys.readouterr()
    assert json.loads(out)["status"] == "budget_shortfall"
    directory = tmp_path / "trial"
    assert main(["experiment", "--source", "signs", "--start", "2027-01-04", "--seed", "published", "--out", str(directory)]) == 0
    capsys.readouterr()
    assert main(["attribute", str(directory / "trial.json"), str(directory / "readings.csv")]) == 2
    _, err = capsys.readouterr()
    assert "status must be" in err
