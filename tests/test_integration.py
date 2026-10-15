"""From export to accountable import: controller limits can cost energy but
never light; approvals bind to the exact files; the CMS readback is checked."""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from vdl7.cli import main
from vdl7.integration import (GATES, adapt_program, adapt_programs, check_program, evaluate_readiness, level_at,
                              never_darker, read_capabilities, reconcile)
from vdl7.schedule import programs

ROOT = Path(__file__).resolve().parents[1]
FOUR_STEP = json.loads((ROOT / "examples/controllers/illustrative-photocell-4step.json").read_text())
SIX_STEP = json.loads((ROOT / "examples/controllers/illustrative-astro-6step.json").read_text())


def caps(**overrides):
    return dict(SIX_STEP, **overrides)


def random_program(rng):
    times = sorted(rng.sample(range(18 * 60, 31 * 60), rng.randint(0, 10)))
    steps = [{"at": "dusk", "level": rng.randint(1, 100)}]
    for t in times:
        steps.append({"at": f"{(t // 60) % 24:02d}:{t % 60:02d}", "level": rng.randint(1, 100)})
    steps.append({"at": "dawn", "level": 0})
    return steps


def test_adaptation_is_never_darker_and_always_fits():
    rng = random.Random(1015)
    for _ in range(300):
        steps = random_program(rng)
        limits = caps(max_steps_per_program=rng.randint(1, 8), time_resolution_min=rng.choice([1, 5, 15, 30, 60]),
                      min_level_pct=rng.choice([0, 10, 25, 30]), level_step_pct=rng.choice([1, 5, 10, 20]))
        adapted = adapt_program(steps, limits)
        assert never_darker(adapted, steps)
        assert check_program(adapted, limits) == []
        assert adapted[0]["at"] == "dusk" and adapted[-1] == {"at": "dawn", "level": 0}


def test_programmes_that_already_fit_are_untouched():
    progs = programs()
    adapted, report = adapt_programs(progs, caps(max_steps_per_program=20))
    assert report["compatible"] and adapted == progs
    assert not any(e["adapted"] for e in report["programs"].values())


def test_dc_arterial_on_a_four_step_node():
    original = programs()["arterial"]["steps"]
    adapted = adapt_program(original, FOUR_STEP)
    assert len(adapted) - 1 <= 4 and never_darker(adapted, original)
    assert all(s["level"] % 10 == 0 for s in adapted[:-1])
    # The deep-night saving survives: still at 60 % at 03:00 where the export asks 58 %.
    assert level_at(adapted, 27 * 60) == 60


def test_a_level_the_node_cannot_reach_is_refused_not_dimmed(tmp_path, capsys):
    limits = caps(max_level_pct=80, level_step_pct=10)
    _, report = adapt_programs(programs(), limits)
    assert not report["compatible"] and any("reaches 80 %" in b for b in report["blocking"])
    profile = tmp_path / "node.json"
    profile.write_text(json.dumps(limits))
    assert main(["schedule", "--controller", str(profile), "--out", str(tmp_path / "p")]) == 1
    assert "refusing to export" in capsys.readouterr().err
    assert not (tmp_path / "p").exists()


def test_too_many_programmes_is_refused():
    _, report = adapt_programs(programs(), caps(max_programs=4))
    assert not report["compatible"] and "programmes" in report["blocking"][0]


@pytest.mark.parametrize("bad", [{"time_resolution_min": 7}, {"level_step_pct": 0}, {"dusk_dawn": ["sundial"]},
                                 {"max_level_pct": 95, "level_step_pct": 10}, {"colour": "red"}])
def test_capability_profiles_are_checked(bad):
    with pytest.raises(ValueError, match="controller profile"):
        read_capabilities(caps(**bad))


def export_package(tmp_path, capsys, controller=FOUR_STEP):
    plan = tmp_path / "plan.csv"
    assert main(["pilot", "--seed", "published", "--out", str(plan)]) == 0
    argv = ["schedule", "--plan", str(plan), "--wave", "1", "--out", str(tmp_path / "phase0")]
    if controller is not None:
        profile = tmp_path / "node.json"
        profile.write_text(json.dumps(controller))
        argv += ["--controller", str(profile)]
    assert main(argv) == 0
    capsys.readouterr()
    return tmp_path / "phase0"


def approve(record_path, **overrides):
    record = json.loads(record_path.read_text())
    for gate in record["gates"]:
        gate.update(status="approved", approved_by="A. Engineer", role="Streetlight programme manager",
                    date="2026-10-01", evidence=f"TICKET-{gate['id']}")
        gate.update(overrides.get(gate["id"], {}))
    record_path.write_text(json.dumps(record, indent=2))


def test_a_fresh_package_is_not_ready_and_says_why(tmp_path, capsys):
    package = export_package(tmp_path, capsys)
    doc = json.loads((package / "programs.json").read_text())
    assert "approval" in doc and doc["controller"]["verified"] is False
    result = evaluate_readiness(package / "readiness.json")
    assert not result["ready"] and len(result["blockers"]) == len(GATES)
    assert main(["readiness", str(package / "readiness.json")]) == 3


def test_approvals_bind_to_the_exact_files(tmp_path, capsys):
    package = export_package(tmp_path, capsys)
    record = package / "readiness.json"
    approve(record)
    assert evaluate_readiness(record)["ready"]
    assert main(["readiness", str(record)]) == 0
    capsys.readouterr()
    programs_file = package / "programs.json"
    programs_file.write_text(programs_file.read_text().replace('"level": 60', '"level": 40', 1))
    result = evaluate_readiness(record)
    assert not result["ready"] and any("changed after this record" in b for b in result["blockers"])


def test_incomplete_or_future_approvals_are_blockers(tmp_path, capsys):
    package = export_package(tmp_path, capsys)
    record = package / "readiness.json"
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    approve(record, photometric={"evidence": ""}, rollback={"date": tomorrow},
            hin={"status": "not_applicable", "evidence": "No HIN segments in this wave (city list v2026-09)"})
    blockers = evaluate_readiness(record)["blockers"]
    assert any(b.startswith("Photometric review") and "evidence" in b for b in blockers)
    assert any(b.startswith("Rollback") and "future" in b for b in blockers)
    assert not any(b.startswith("High-Injury") for b in blockers)


def test_without_a_controller_profile_compatibility_blocks_import(tmp_path, capsys):
    package = export_package(tmp_path, capsys, controller=None)
    approve(package / "readiness.json")
    result = evaluate_readiness(package / "readiness.json")
    assert result["blockers"] == ["compatibility: no controller capability profile: rerun `nocturne schedule --controller`"]


def test_a_rerun_never_overwrites_recorded_approvals(tmp_path, capsys):
    package = export_package(tmp_path, capsys)
    approve(package / "readiness.json")
    before = (package / "readiness.json").read_text()
    assert main(["schedule", "--floor", "40", "--out", str(package)]) == 0
    assert "kept the existing" in capsys.readouterr().err
    assert (package / "readiness.json").read_text() == before
    assert not evaluate_readiness(package / "readiness.json")["ready"]       # the programmes changed under it


def write_readback(tmp_path, package, edit_program=None, edit_rows=None):
    doc = json.loads((package / "programs.json").read_text())
    progs = {name: {"steps": p["steps"]} for name, p in doc["programs"].items()}
    if edit_program:
        edit_program(progs)
    (tmp_path / "cms.json").write_text(json.dumps({"programs": progs}))
    with open(package / "assignments-wave1.csv", newline="") as f:
        rows = [{"segment": r["segment"], "program": r["program"]} for r in csv.DictReader(f)]
    if edit_rows:
        rows = edit_rows(rows)
    with open(tmp_path / "cms.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["segment", "program"])
        w.writeheader()
        w.writerows(rows)
    return ["reconcile", "--programs", str(package / "programs.json"),
            "--assignments", str(package / "assignments-wave1.csv"),
            "--cms-programs", str(tmp_path / "cms.json"), "--cms-assignments", str(tmp_path / "cms.csv")]


def test_reconcile_accepts_an_exact_load(tmp_path, capsys):
    package = export_package(tmp_path, capsys)
    assert main(write_readback(tmp_path, package)) == 0
    assert "3,024 of 3,024" in capsys.readouterr().out


def test_reconcile_flags_missing_and_darker_segments(tmp_path, capsys):
    package = export_package(tmp_path, capsys)

    def darker_local(progs):
        progs["local"]["steps"] = [{"at": "dusk", "level": 80}, {"at": "22:00", "level": 30}, {"at": "dawn", "level": 0}]

    argv = write_readback(tmp_path, package, darker_local, lambda rows: rows[1:])
    assert main(argv + ["--json"]) == 3
    result = json.loads(capsys.readouterr().out)
    assert any("not in the CMS readback" in e for e in result["errors"])
    assert any("darker than intended" in e and "22:00" in e for e in result["errors"])


def test_reconcile_warns_on_brighter_or_remapped_programmes():
    progs = programs()
    want = {"local": progs["local"]["steps"]}
    held = {"hin/local": progs["hin/local"]["steps"], "local": progs["local"]["steps"]}
    result = reconcile(want, [("S1", "local"), ("S2", "local")], held, {"S1": "hin/local", "S2": "local", "S9": "local"})
    assert result["ok"] and result["matched"] == 2
    assert any("instead of 'local'" in w for w in result["warnings"])
    assert any("not in this wave" in w for w in result["warnings"])
