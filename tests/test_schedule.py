"""Phase 0 programmes for the networked nodes DC already has.

`EXT-P0-*` check the programmes keep every floor, never sit below the
signed profile, read correctly across midnight, export cleanly, and are
exactly what the business case integrates.
"""
from __future__ import annotations

import json

import pytest

from vdl7.annual import _walk_boost, expected_level
from vdl7.profiles import DEFAULT_PROFILES, PHASE_ORDER, RoadClass, default_bundle, phase_for_hour
from vdl7.schedule import SCHEMA, export, level_at, program, programs

HOURS = [18.5, 19.5, 20.5, 21.5, 22.25, 22.75, 23.5, 0.25, 0.75, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5]


@pytest.mark.parametrize("road", list(RoadClass))
def test_EXT_P0_1_programmes_keep_every_floor_and_the_signed_levels(road):
    prof = DEFAULT_PROFILES[road]
    steps = program(prof, unsensed_floor=50.0)
    assert steps[0].at == "dusk" and steps[-1].at == "dawn" and steps[-1].level == 0
    assert all(a.level != b.level for a, b in zip(steps[:-1], steps[1:-1]))          # no no-op steps
    for h in HOURS:
        lv = level_at(steps, h)
        base = prof.levels[PHASE_ORDER.index(phase_for_hour(h))]
        assert lv >= base and lv >= prof.floor and lv <= 100, (road, h, lv)
        if not prof.design_volume:
            assert lv >= 50.0                                                          # unsensed floor


def test_EXT_P0_2_arterials_step_hourly_with_expected_traffic():
    steps = program(DEFAULT_PROFILES[RoadClass.ARTERIAL])
    assert [s.at for s in steps][:3] == ["dusk", "22:00", "23:00"]
    assert level_at(steps, 23.5) > DEFAULT_PROFILES[RoadClass.ARTERIAL].base(PHASE_ORDER[2])    # traffic lifts the curfew
    assert level_at(steps, 2.5) < level_at(steps, 23.5) < level_at(steps, 22.5)               # and fades with it
    assert level_at(steps, 6.5) > level_at(steps, 3.5)                                         # morning traffic


def test_EXT_P0_2b_traffic_steps_run_on_to_the_latest_dawns():
    """Paris dawns as late as 08:28 and Tromso's near 11:30: the arterial
    programme keeps stepping with the morning traffic instead of holding
    its 06:00 level until dawn."""
    steps = program(DEFAULT_PROFILES[RoadClass.ARTERIAL])
    assert "07:00" in [s.at for s in steps]
    assert level_at(steps, 8.0) >= level_at(steps, 6.5) and level_at(steps, 8.0) == 100


def test_EXT_P0_3_level_lookup_crosses_midnight():
    steps = program(DEFAULT_PROFILES[RoadClass.LOCAL])
    assert level_at(steps, 21.9) == 80 and level_at(steps, 22.1) == 60
    assert level_at(steps, 23.9) == 50 and level_at(steps, 0.1) == 50 and level_at(steps, 4.0) == 50


def test_EXT_P0_4_export_and_zones():
    bd = default_bundle(version=4)
    bd.zones = {"rock-creek-buffer": {RoadClass.LOCAL: (60, 40, 30, 30, 30)}}
    doc = json.loads(export(bd, tz="EST5EDT,M3.2.0,M11.1.0", unsensed_floor=50.0))
    assert doc["schema"] == SCHEMA and doc["bundle_version"] == 4
    zone = doc["programs"]["rock-creek-buffer/local"]
    assert zone["zone"] == "rock-creek-buffer" and [s["level"] for s in zone["steps"]] == [60, 50, 0]
    assert {k for k in programs() if not k.startswith("hin/")} == {r.value for r in RoadClass}


def test_EXT_P0_4b_high_injury_network_programmes_keep_the_hin_floor():
    """A Phase 0 export must not dim a High-Injury Network segment below the
    floor the firmware would hold it at."""
    bd = default_bundle()
    bd.zones = {"rock-creek-buffer": {RoadClass.LOCAL: (60, 40, 30, 30, 30)}}
    progs = programs(bd, 50.0)
    for road in RoadClass:
        plain = [s["level"] for s in progs[road.value]["steps"][:-1]]
        hin = progs.get(f"hin/{road.value}")
        if min(plain) >= bd.hin_floor:
            assert hin is None
            continue
        assert hin["hin"] and min(s["level"] for s in hin["steps"][:-1]) >= bd.hin_floor
        assert hin["steps"][-1] == {"at": "dawn", "level": 0}
    assert min(s["level"] for s in progs["rock-creek-buffer/hin/local"]["steps"][:-1]) == bd.hin_floor
    doc = json.loads(export(bd))
    assert doc["hin_floor_pct"] == bd.hin_floor and "hin/arterial" in doc["programs"]


@pytest.mark.parametrize("road", list(RoadClass))
def test_EXT_P0_5_the_business_case_integrates_exactly_these_programmes(road):
    prof, w = DEFAULT_PROFILES[road], _walk_boost(21.4)
    steps = program(prof, 50.0)
    for h in HOURS:
        base = float(prof.levels[PHASE_ORDER.index(phase_for_hour(h))])
        assert expected_level(prof, base, h, "schedule", 50.0, w) == level_at(steps, h)


def test_EXT_P0_6_floors_and_zone_files_are_checked(tmp_path):
    """A floor outside 0-100 % or a fractional zone level is refused, never
    turned into a programme or rounded into a valid-looking bundle."""
    from vdl7.annual import dc_fleet, run_year
    from vdl7.cli import main
    for bad in (150.0, -1.0, float("nan")):
        with pytest.raises(ValueError, match="floor"):
            program(DEFAULT_PROFILES[RoadClass.LOCAL], bad)
        with pytest.raises(ValueError, match="floor"):
            run_year(dc_fleet(), unsensed_floor=bad, days=("2027-01-10", "2027-01-10"))
    with pytest.raises(SystemExit):
        main(["schedule", "--floor", "150", "--out", str(tmp_path / "p")])
    for levels in ([80.9, 60.9, 40.9, 30.9, 50.9], [100.9, 60, 40, 30, 50]):
        z = tmp_path / "zones.json"
        z.write_text(json.dumps({"rock-creek-buffer": {"local": levels}}))
        with pytest.raises(SystemExit, match="zones"):
            main(["schedule", "--zones", str(z), "--out", str(tmp_path / "p")])
    z.write_text(json.dumps({"rock-creek-buffer": {"local": [60, 40, 30, 30, 30]}}))
    assert main(["schedule", "--zones", str(z), "--out", str(tmp_path / "p")]) == 0
