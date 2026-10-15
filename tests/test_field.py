"""Field pilot gating checks, including trial integrity and safety declarations."""
import copy
import json
from pathlib import Path

import pytest

from vdl7.attribution import make_trial
from vdl7.cli import main
from vdl7.field import REQUIRED_CHECKS, audit


def trial():
    return make_trial(["facade"], "2027-01-04", "fixed-before-observation", pairs=6, dim_fraction=0)


def manifest(t):
    return {
        "schema": "nocturne-field-pilot/1",
        "site_id": "site-a",
        "source": "facade",
        "trial_sha256": t["trial_sha256"],
        "synthetic": False,
        "checks": {key: {"status": "pending", "evidence": ""} for key in REQUIRED_CHECKS},
    }


def test_pending_never_passes_and_all_checks_named():
    t = trial()
    result = audit(manifest(t), t)
    assert not result["ready_to_collect"]
    assert len(result["blockers"]) == len(REQUIRED_CHECKS)
    assert "Self-reported" in result["claim"]


def test_complete_declarations_pass_without_claiming_field_effect():
    t = trial()
    m = manifest(t)
    for check in m["checks"].values():
        check.update(status="confirmed", evidence="Local signed operator record, not included in repository")
    result = audit(m, t)
    assert result["ready_to_collect"] and result["blockers"] == []
    assert "observed skyglow reduction" in result["claim"]


def test_hash_source_and_synthetic_gate():
    t = trial()
    m = manifest(t)
    for check in m["checks"].values():
        check.update(status="confirmed", evidence="Record")
    for change in ({"trial_sha256": "wrong"}, {"source": "not-in-trial"}, {"synthetic": True}):
        bad = copy.deepcopy(m)
        bad.update(change)
        assert not audit(bad, t)["ready_to_collect"]
    altered = copy.deepcopy(t)
    altered["seed"] = "changed"
    with pytest.raises(ValueError, match="fingerprint|hash|preregister"):
        audit(m, altered)


def test_invalid_flags_and_missing_evidence():
    t = trial()
    m = manifest(t)
    m["checks"]["owner_permission"] = {"status": "confirmed", "evidence": ""}
    assert not audit(m, t)["ready_to_collect"]
    m["checks"]["owner_permission"]["status"] = True
    with pytest.raises(ValueError, match="pending/confirmed"):
        audit(m, t)


def test_cli_returns_three_for_pending_and_zero_for_complete(tmp_path, capsys):
    t = trial()
    m = manifest(t)
    tp, mp = tmp_path / "trial.json", tmp_path / "manifest.json"
    tp.write_text(json.dumps(t))
    mp.write_text(json.dumps(m))
    assert main(["field-check", str(mp), str(tp)]) == 3
    assert json.loads(capsys.readouterr().out)["ready_to_collect"] is False
    for check in m["checks"].values():
        check.update(status="confirmed", evidence="Local evidence reference")
    mp.write_text(json.dumps(m))
    assert main(["field-check", str(mp), str(tp)]) == 0
    assert json.loads(capsys.readouterr().out)["ready_to_collect"] is True
