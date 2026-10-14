"""File formats in and out: LM-63 editions, plan and assignment CSVs,
iCalendar UIDs, and photometer logs without a header."""
import csv
from datetime import date

import pytest

from vdl7.nightsignal import signal, to_ics
from vdl7.observe import read_sqm
from vdl7.photometry import parse_ies, synthetic, write_ies
from vdl7.pilot import Segment, load_plan, stepped_wedge
from vdl7.sites import SITES

GLOBE = write_ies(synthetic("globe", 4000, ulr=0.0, watts=40), watts=40)      # IESNA:LM-63-2002, "1 1 40"


def _edition(header: str, second: str) -> str:
    text = GLOBE.replace("\n1 1 40\n", f"\n1 {second} 40\n")
    assert text != GLOBE
    lines = text.split("\n")
    return "\n".join(([header] if header else []) + lines[1:])


def test_FMT_1_lm63_2019_file_generation_type_is_not_a_multiplier():
    """In LM-63-2019 the second value of the ballast line is the file
    generation type (1.10000 = accredited laboratory). Reading it as the old
    ballast-lamp factor added 10 % to every candela and turned this U0
    globe's G2 into G3."""
    base = parse_ies(GLOBE)
    p = parse_ies(_edition("IES:LM-63-2019", "1.10000"))
    assert p.zonal_lumens()["total"] == pytest.approx(base.zonal_lumens()["total"], rel=1e-9)
    assert p.zonal_lumens()["total"] == pytest.approx(4000, rel=1e-3)
    assert str(p.bug()) == str(base.bug()) == "B2-U0-G2"
    assert p.file_generation_type == pytest.approx(1.1) and base.file_generation_type is None
    q = parse_ies(_edition("IESNA:LM-63-2002", "1.10000"))               # 'future use' in 2002: ignored
    assert q.zonal_lumens()["total"] == pytest.approx(4000, rel=1e-3) and q.file_generation_type is None


@pytest.mark.parametrize("header", ["IESNA:LM-63-1995", "IESNA91", "﻿IESNA:LM-63-1995", ""])
def test_FMT_2_older_editions_still_apply_the_ballast_lamp_factor(header):
    """Up to LM-63-1995 (and the 1986 format, with no edition line) the
    value is the ballast-lamp photometric factor and scales the candela."""
    p = parse_ies(_edition(header, "0.5"))           # header "": the 1986 format, keywords straight away
    assert p.zonal_lumens()["total"] == pytest.approx(2000, rel=1e-3)


def test_FMT_3_plan_and_assignment_csvs_quote_their_fields(tmp_path):
    """A ward named with a comma used to shift every later column: the wave
    read back as 3 and the switch-on date as '1'."""
    segs = [Segment("A1", "Ward 1, North", "local", 4, 0.2), Segment("A2", "Ward 1, North", "local", 3, 0.1),
            Segment("B1", "Ward 2", "arterial", 5, 0.5), Segment("B2", 'Ward "2"', "arterial", 6, 0.6)]
    plan = stepped_wedge(segs, "s")
    path = tmp_path / "plan.csv"
    plan.to_csv(str(path), segs)
    rows = load_plan(str(path))
    assert {r["segment"]: r["ward"] for r in rows} == {s.id: s.ward for s in segs}
    for r in rows:
        assert int(r["wave"]) == plan.assignment[r["segment"]]
        assert date.fromisoformat(r["switch_on"]) == plan.wave_start(int(r["wave"]))
    assert path.read_text().startswith("segment,ward,road_class,lights,wave,switch_on\n")
    assert "\r" not in path.read_text()

    from vdl7.cli import main
    assert main(["schedule", "--plan", str(path), "--out", str(tmp_path / "p0")]) == 0
    with open(tmp_path / "p0" / "assignments.csv", newline="") as f:
        got = list(csv.DictReader(f))
    assert [(r["segment"], r["ward"], r["program"]) for r in got] == [
        (r["segment"], r["ward"], r["road_class"]) for r in rows]


def test_FMT_4_plan_files_are_checked(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("segment,ward\nA1,1\n")
    with pytest.raises(ValueError, match="not a plan"):
        load_plan(str(bad))
    bad.write_text("segment,ward,road_class,lights,wave,switch_on\nA1,1,local,3,1,soon\n")
    with pytest.raises(ValueError, match="row 2"):
        load_plan(str(bad))


def test_FMT_5_calendar_uids_name_the_site():
    """RFC 5545 UIDs are global: DC's and London's curfew on the same night
    are different events and must not share one."""
    night = date(2026, 10, 14)
    uids = {}
    for key in ("dc", "london"):
        ics = to_ics([signal(night, site=SITES[key])])
        uids[key] = [ln for ln in ics.split("\r\n") if ln.startswith("UID:")]
    assert uids["dc"] == ["UID:2026-10-14-curfew@nocturne-dc"]
    assert uids["london"] == ["UID:2026-10-14-curfew@nocturne-london"]
    doc = signal(night)
    doc["site"] = {k: v for k, v in doc["site"].items() if k != "key"}       # a document without a key
    assert "UID:2026-10-14-curfew@nocturne-38.8977_-77.0365" in to_ics([doc])


def test_FMT_6_headerless_logs_pick_msas_not_a_constant_column(tmp_path):
    """A TESS-W row ends ...;Frequency;MSAS;ZP. Without the header, the
    rightmost 10-25 value was the zero point (a constant 20.44), not the
    sky. A column that never changes is not the sky."""
    tess = tmp_path / "tess.dat"
    tess.write_text("2026-10-14T03:00:00.000;2026-10-13T23:00:00.000;12.1;-20.3;3.21;18.73;20.44\n"
                    "2026-10-14T03:05:00.000;2026-10-13T23:05:00.000;12.0;-20.4;3.10;18.77;20.44\n")
    assert [m for _, m in read_sqm(str(tess))] == pytest.approx([18.73, 18.77])
    sqm = tmp_path / "sqm.dat"                       # SQM-LU-DL: ...;Counts;Frequency;MSAS
    sqm.write_text("2026-10-14T03:00:00.000;2026-10-13T23:00:00.000;14.0;0.00;14.10;18.61\n"
                   "2026-10-14T03:05:00.000;2026-10-13T23:05:00.000;14.0;0.00;13.20;18.69\n")
    assert [m for _, m in read_sqm(str(sqm))] == pytest.approx([18.61, 18.69])
    named = tmp_path / "named.dat"                   # a header row that lacks its '#'
    named.write_text("UTC;Local;Temperature;MSAS;ZP\n2026-10-14T03:00:00;2026-10-13T23:00:00;12;18.5;20.44\n")
    assert [m for _, m in read_sqm(str(named))] == [18.5]


def test_FMT_7_an_undecidable_headerless_log_asks_for_its_header(tmp_path):
    one = tmp_path / "one.dat"                       # one reading: temperature and MSAS both fit
    one.write_text("2026-10-14T03:00:00.000;2026-10-13T23:00:00.000;12.0;0.00;18.73\n")
    with pytest.raises(ValueError, match="header"):
        read_sqm(str(one))
    none = tmp_path / "none.dat"
    none.write_text("2026-10-14T03:00:00.000;2026-10-13T23:00:00.000;1.0;0.00;3.2\n")
    with pytest.raises(ValueError, match="10-25 mag"):
        read_sqm(str(none))
