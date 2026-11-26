"""Astronomy planning is a read-only screen, not the trial's field gate."""
import json
from datetime import datetime
from types import SimpleNamespace

from vdl7 import attribution
from vdl7.cli import main
from vdl7.clock import DC_LAT, DC_LON


def trial(start):
    return attribution.make_trial(["facade"], start, "fixed", 12, dim_fraction=0)


def test_example_dates_and_night_count():
    old = attribution.sky_preflight(trial("2027-01-04"), DC_LAT, DC_LON)
    assert old["planned_pairs"] == 12
    assert old["ephemeris_eligible_pairs"] == 10
    assert {(w["night"], w["period"]) for w in old["flagged_windows"]} == {
        (night, period) for night in ("2027-01-14", "2027-01-15") for period in (1, 2)
    }
    assert all(w["flags"] == ["moon_not_below_limit"] for w in old["flagged_windows"])
    new = attribution.sky_preflight(trial("2027-01-30"), DC_LAT, DC_LON)
    assert new["planned_pairs"] == new["ephemeris_eligible_pairs"] == 12
    assert not new["flagged_windows"]


def test_second_window_endpoint_counts(monkeypatch):
    t = trial("2027-01-30")
    endpoint = datetime.fromisoformat(t["assignments"][1]["end_utc"])
    monkeypatch.setattr(attribution, "solar_elevation_exact", lambda lat, lon, at: -18 if at == endpoint else -19)
    monkeypatch.setattr(attribution, "moon", lambda at, lat, lon: SimpleNamespace(alt_deg=-20))
    result = attribution.sky_preflight(t, DC_LAT, DC_LON)
    assert result["ephemeris_eligible_pairs"] == 11
    assert len(result["flagged_windows"]) == 1
    assert result["flagged_windows"][0]["period"] == 2
    assert result["flagged_windows"][0]["flags"] == ["sun_not_below_limit"]


def test_cli_exit_and_no_trial_changes(tmp_path, capsys):
    file = tmp_path / "trial.json"
    args = ["trial-sky", str(file), "--lat", str(DC_LAT), "--lon", str(DC_LON)]
    for start, code in [("2027-01-04", 3), ("2027-01-30", 0)]:
        t = trial(start)
        original = json.dumps(t)
        file.write_text(original)
        assert main(args) == code
        assert json.loads(capsys.readouterr().out)["trial_sha256"] == t["trial_sha256"]
        assert file.read_text() == original
    assert main(args[:-1] + ["nan"]) == 2
    assert "longitude" in capsys.readouterr().err
    t["seed"] = "tampered"
    file.write_text(json.dumps(t))
    assert main(args) == 2
    assert "fingerprint" in capsys.readouterr().err
