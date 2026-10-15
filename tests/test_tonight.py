"""Owner boundaries, honest credit, DST, and plan-bound evidence for DC Tonight."""
import copy
import json

import pytest

from vdl7.cli import main
from vdl7.tonight import (RECEIPT_FIELDS, calendar, example_project, plan, read_receipts,
                         receipt_template, reconcile, render, write_packet)


def project():
    return example_project("2026-10-15")


def completed(p, aid="facade"):
    result = plan(p)
    a = next(a for a in result["actions"] if a["id"] == aid)
    return dict({k: "" for k in RECEIPT_FIELDS}, plan_sha256=result["plan_sha256"], action_id=aid,
                status="completed", started_at=a["start_at"], ended_at=a["end_at"], observer="Fictional operator",
                evidence="Synthetic switch log and morning walkthrough", service_preserved="yes", no_rebound="yes")


def test_ownership_not_wattage_decides_what_can_happen():
    p = project()
    r = plan(p)
    assert [a["status"] for a in r["actions"]] == ["owner_ready", "owner_ready", "needs_owner_check", "request_only"]
    assert r["potential_kwh"] == pytest.approx(4.8)
    assert r["containment_hours"] == 8 and r["ready_count"] == 2
    for authority in ("district", "federal", "unknown"):
        p["actions"][0]["authority"] = authority
        assert plan(p)["actions"][0]["status"] == "request_only"
        assert plan(p)["potential_kwh"] == 0


@pytest.mark.parametrize("key,value", [("authorized", False), ("owner", ""), ("circuit", ""),
    ("service_reviewed", False), ("preserve", ""), ("existing_control", False), ("baseline_on", False),
    ("rollback", ""), ("evidence", "")])
def test_missing_conditions_do_not_turn_into_tasks_or_calendar_events(key, value):
    p = project()
    p["actions"][0][key] = value
    r = plan(p)
    assert r["actions"][0]["status"] == "needs_owner_check"
    assert r["potential_kwh"] == 0
    assert "-facade-start@" not in calendar(r)


def test_unknown_power_is_unknown_and_blinds_get_no_energy_credit():
    p = project()
    p["actions"][0]["watts"] = None
    p["actions"][1]["watts"] = 500000
    r = plan(p)
    assert r["ready_count"] == 2 and r["unquantified_count"] == 1 and r["potential_kwh"] == 0
    actual = reconcile(p, [completed(p), completed(p, "windows")])
    assert actual["unquantified_count"] == 1 and actual["estimated_kwh"] == 0
    assert actual["containment_hours"] == 8
    p["actions"][0]["watts"] = 600
    p["actions"][0]["power_basis"] = ""
    assert plan(p)["unquantified_count"] == 1


@pytest.mark.parametrize("night,hours", [("2026-03-07", 7), ("2026-10-31", 9), ("2026-10-15", 8)])
def test_actual_elapsed_time_across_dc_daylight_saving(night, hours):
    p = example_project(night)
    assert plan(p)["actions"][0]["hours"] == hours
    assert reconcile(p, [completed(p)])["estimated_kwh"] == pytest.approx(hours * .6)


@pytest.mark.parametrize("night,clock", [("2026-03-07", "02:30"), ("2026-10-31", "01:30")])
def test_ambiguous_and_nonexistent_clock_times_are_not_guessed(night, clock):
    p = example_project(night)
    p["actions"][0]["end"] = clock
    with pytest.raises(ValueError, match="missing or repeated"):
        plan(p)


def test_receipts_do_not_claim_work_from_an_empty_ledger():
    p = project()
    ledger = read_receipts(receipt_template(plan(p)))
    r = reconcile(p, ledger)
    assert r["unconfirmed_count"] == 2 and r["completed_count"] == 0 and r["estimated_kwh"] == 0
    assert not any(row["started_at"] for row in ledger)


def test_partial_completion_counts_only_the_reviewed_recorded_interval():
    p = project()
    receipt = completed(p)
    receipt["started_at"] = "2026-10-16T00:00:00-04:00"
    receipt["ended_at"] = "2026-10-16T05:00:00-04:00"
    r = reconcile(p, [receipt])
    assert r["estimated_kwh"] == 3 and r["completed_count"] == 1 and r["unconfirmed_count"] == 1
    receipt["started_at"] = "2026-10-15T21:00:00-04:00"
    with pytest.raises(ValueError, match="within"):
        reconcile(p, [receipt])


@pytest.mark.parametrize("field,value", [("service_preserved", "no"), ("no_rebound", "no"), ("no_rebound", "")])
def test_service_loss_or_rebound_withholds_credit(field, value):
    p = project()
    receipt = completed(p)
    receipt[field] = value
    r = reconcile(p, [receipt])
    assert r["review_count"] == 1 and r["completed_count"] == 0 and r["estimated_kwh"] == 0


def test_edited_plans_duplicates_and_unapproved_actions_cannot_reuse_receipts():
    p = project()
    receipt = completed(p)
    altered = copy.deepcopy(p)
    altered["actions"][0]["watts"] = 6000
    with pytest.raises(ValueError, match="another plan"):
        reconcile(altered, [receipt])
    with pytest.raises(ValueError, match="already recorded"):
        reconcile(p, [receipt, receipt])
    receipt["action_id"] = "sign"
    with pytest.raises(ValueError, match="not an owner-ready"):
        reconcile(p, [receipt])


@pytest.mark.parametrize("change", [{"watts": float("nan")}, {"watts": float("inf")}, {"watts": -1}, {"watts": 10**400},
    {"watts": True}, {"authorized": "true"}, {"kind": "dim"}, {"start": "25:00"},
    {"end": "21:00"}, {"label": "bad\r\nBEGIN:VEVENT"}])
def test_invalid_inputs_are_actionable_errors(change):
    p = project()
    p["actions"][0].update(change)
    with pytest.raises(ValueError, match="actions"):
        plan(p)


def test_a_circuit_cannot_be_double_counted():
    p = project()
    p["actions"][1]["circuit"] = "EXAMPLE-FACADE"
    with pytest.raises(ValueError, match="double-counting"):
        plan(p)


def test_malformed_receipt_csv_is_a_readable_input_error():
    header = ",".join(RECEIPT_FIELDS) + "\n"
    with pytest.raises(ValueError, match="receipts CSV"):
        read_receipts(header + '"unterminated')
    with pytest.raises(ValueError, match="receipts CSV"):
        read_receipts(header + "extra,columns")


def test_markup_escaped_calendar_folded_and_only_ready_actions_exported():
    p = project()
    p["actions"][0]["label"] = '<script>alert("x")</script> & 🌙' * 10
    result = plan(p)
    page = render(result)
    assert "<script>" not in page and "&lt;script&gt;" in page
    ics = calendar(result)
    assert ics.count("BEGIN:VEVENT") == 4 and "[FICTIONAL DEMO]" in ics
    assert "-sign-start@" not in ics and "-street-start@" not in ics
    assert all(len(line.encode()) <= 75 for line in ics.splitlines())
    assert "DTSTART:20261016T020000Z" in ics and "DTSTART:20261016T100000Z" in ics


def test_packet_and_cli_round_trip_without_overwriting_evidence(tmp_path, capsys):
    directory = tmp_path / "packet"
    p = project()
    result = write_packet(p, directory)
    assert set(x.name for x in directory.iterdir()) == {"project.json", "plan.json", "action-sheet.html", "handoff.ics", "receipts.csv"}
    assert plan(json.loads((directory / "project.json").read_text()))["plan_sha256"] == result["plan_sha256"]
    with pytest.raises(FileExistsError):
        write_packet(p, directory)
    assert main(["receipts", str(directory / "project.json"), str(directory / "receipts.csv")]) == 3
    assert json.loads(capsys.readouterr().out)["estimated_kwh"] == 0
    assert main(["tonight", "--example", "--date", "2026-10-15"]) == 0
    assert json.loads(capsys.readouterr().out)["plan_sha256"] == result["plan_sha256"]
