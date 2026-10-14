"""The command line: machine-readable output stays machine-readable, bad
input gets a one-line error (exit 2, argparse's convention) instead of a
traceback, and options that used to be ignored now act or are refused."""
import json
import os

import pytest

from vdl7.bench import Bench
from vdl7.cli import main
from vdl7.events import EventKind
from vdl7.pilot import exposure_needed, stepped_wedge

ROOT = os.path.join(os.path.dirname(__file__), "..")
IES = os.path.join(ROOT, "examples", "ies", "synthetic-roadway-6000lm-u0.ies")


def run(argv, capsys):
    try:
        code = main(argv)
    except SystemExit as e:                          # argparse's own errors
        code = e.code
    out, err = capsys.readouterr()
    return code, out, err


def test_CLI_1_signal_with_a_feed_prints_only_json(tmp_path, capsys):
    ics = tmp_path / "curfew.ics"
    code, out, err = run(["signal", "--date", "2026-10-14", "--ics", str(ics), "--days", "3"], capsys)
    assert code == 0 and json.loads(out)["night_of"] == "2026-10-14"
    assert "wrote" in err and ics.read_text().count("BEGIN:VEVENT") == 3


def test_CLI_2_sky_json_with_retrofits_is_one_document(capsys):
    code, out, _ = run(["sky", "--json", "--place", "rock-creek", "--retrofits", "1"], capsys)
    doc = json.loads(out)
    assert code == 0 and set(doc) == {"places", "retrofits"}
    assert [r["place"] for r in doc["places"]] == ["rock-creek", "rock-creek"]
    assert len(doc["retrofits"]) == 1 and set(doc["retrofits"][0]) >= {"lat", "lon", "globes_kw", "gain"}


BAD = [
    (["signal", "--date", "tomorrow"], "not a date"),
    (["signal", "--key", "{tmp}/missing.pem"], "No such file"),
    (["verify", "{tmp}/missing.dat", "--go-live", "2026-11-01"], "No such file"),
    (["verify", "{tmp}/missing.dat", "--go-live", "2026-13-01"], "not a date"),
    (["bug", "{tmp}/missing.ies"], "No such file"),
    (["bug", os.path.join(ROOT, "README.md")], "TILT"),
    (["pilot", "--power", "0.0014", "1"], "not 1"),
    (["pilot", "--power", "0.0014", "abc"], "not a number"),
    (["pilot", "--power", "0", "1.2"], "greater than 0"),
    (["pilot", "--seed", "x", "--waves", "0"], "at least 1"),
    (["pilot", "--seed", "x", "--start", "2027-02-30"], "not a date"),
    (["pilot", "--seed", "x", "--segments", "{tmp}/none.csv"], "No such file"),
    (["business-case", "--price", "-0.13"], "negative"),
    (["business-case", "--fleet", "spec", "--lights", "0"], "at least 1"),
    (["sky", "--share", "0"], "share"),
    (["sky", "--place", "rockcreek"], "known: rock-creek"),
    (["sky", "--measured", "rockcreek=18.4"], "known: rock-creek"),
    (["sky", "--measured", "rock-creek=abc"], "place=msas"),
    (["trace", "--event", "emergency"], "kind@HH:MM"),
    (["trace", "--event", "bogus@23:00"], "unknown event kind"),
    (["trace", "--event", "override@23:00"], "needs a level"),
    (["trace", "--offline-at", "9:15pm"], "H:MM"),
    (["trace", "--every", "0"], "at least 1"),
    (["trace", "--start", "yesterday"], "local date and time"),
    (["trace", "--start", "2026-10-14 08:00", "--end", "2026-10-13 18:00"], "not after"),
    (["schedule", "--wave", "2", "--out", "{tmp}/p"], "--plan"),
    (["schedule", "--plan", "{tmp}/none.csv", "--out", "{tmp}/p"], "No such file"),
    (["brake", "--plan", "{tmp}/none.csv", "--crashes", "x.csv", "--through", "2027-02-28"], "No such file"),
    (["trespass", IES, "--height", "-1"], "greater than 0"),
    (["simulate", "--scenario", "bogus", "--out", "{tmp}/s"], "unknown scenario"),
    (["spectral", "--spd", "foo"], "name=path.csv"),
]


@pytest.mark.parametrize("argv,says", BAD, ids=[" ".join(a[:3]) for a, _ in BAD])
def test_CLI_3_bad_input_is_a_message_not_a_traceback(argv, says, tmp_path, capsys):
    code, out, err = run([x.replace("{tmp}", str(tmp_path)) for x in argv], capsys)
    assert code == 2
    assert "error:" in err and says in err and "Traceback" not in err
    last = err.strip().splitlines()[-1]
    assert last.startswith("nocturne") and "error:" in last


def test_CLI_4_brake_input_files_are_checked(tmp_path, capsys):
    plan = tmp_path / "plan.csv"
    plan.write_text("segment,ward,road_class,lights,wave,switch_on\nA,1,local,3,1,2027-01-04\n"
                    "B,1,local,3,2,2027-03-01\n")
    crashes = tmp_path / "crashes.csv"
    crashes.write_text("segment,when\nA,2027-01-05\n")
    code, _, err = run(["brake", "--plan", str(plan), "--crashes", str(crashes), "--through", "2027-02-01"], capsys)
    assert code == 2 and "segment,night" in err
    crashes.write_text("segment,night\nA,last tuesday\n")
    code, _, err = run(["brake", "--plan", str(plan), "--crashes", str(crashes), "--through", "2027-02-01"], capsys)
    assert code == 2 and "row 2" in err
    crashes.write_text("segment,night\nA,2027-01-05\n")
    code, out, _ = run(["brake", "--plan", str(plan), "--crashes", str(crashes), "--through", "2027-02-01"], capsys)
    assert code == 0 and "continue" in out


def test_CLI_5_trace_times_without_a_leading_zero_and_after_midnight(capsys):
    """'1:30' and '0:40' used to be compared as text with '01:30' and
    '00:40' and never fired; they are clock times on the night's own
    timeline."""
    code, out, _ = run(["trace", "--road", "arterial", "--start", "2026-10-14 00:30", "--end", "2026-10-14 01:45",
                        "--offline-at", "1:30", "--event", "emergency@0:40:60"], capsys)
    assert code == 0
    assert "--- event emergency at 00:40 via backhaul, ttl 60 min" in out
    assert "--- backhaul lost at 01:30" in out
    code, out, err = run(["trace", "--start", "2026-10-13 18:00", "--end", "2026-10-13 19:00", "--dt", "60",
                          "--event", "emergency@17:00"], capsys)
    assert code == 0 and "--- event" not in out and "warning" in err and "after --end" in err


@pytest.mark.parametrize("every,rows", [(120, ["18:00", "20:00", "22:00"]),
                                        (25, ["18:00", "18:25", "18:50", "19:15", "19:40"]),
                                        (15, ["18:00", "18:15", "18:30", "18:45", "19:00", "19:15", "19:30", "19:45"])])
def test_CLI_6_trace_rows_every_n_minutes_from_the_start(every, rows, capsys):
    end = "2026-10-14 00:00" if every == 120 else "2026-10-13 20:00"
    code, out, _ = run(["trace", "--every", str(every), "--dt", "60", "--start", "2026-10-13 18:00", "--end", end],
                       capsys)
    assert code == 0 and [ln.split()[0] for ln in out.splitlines()[1:]] == rows


def test_CLI_7_schedule_warns_when_a_wave_has_no_segments(tmp_path, capsys):
    plan = tmp_path / "plan.csv"
    plan.write_text("segment,ward,road_class,lights,wave,switch_on\nA,1,local,3,1,2027-01-04\n")
    code, _, err = run(["schedule", "--plan", str(plan), "--wave", "9", "--out", str(tmp_path / "p")], capsys)
    assert code == 0 and "warning" in err and "wave 9" in err and "1" in err
    assert (tmp_path / "p" / "assignments-wave9.csv").read_text() == "segment,ward,road_class,lights,program,switch_on\n"


def test_CLI_8_library_checks_behind_the_cli():
    with pytest.raises(ValueError, match="not 1"):
        exposure_needed(0.0014, 1.0)
    with pytest.raises(ValueError, match="rate"):
        exposure_needed(0.0, 1.2)
    with pytest.raises(ValueError, match="waves"):
        stepped_wedge([], "x", waves=0)
    with pytest.raises(ValueError, match="refused the override"):     # was an assert: gone under python -O
        Bench().send(EventKind.OVERRIDE, 600, {})
