"""Any city, any latitude, any neighbourhood.

`EXT-CLK-*`  the POSIX TZ engine against the IANA database for every zone on
             Earth, and the controller at latitudes where the sun never sets
             or never rises.
`EXT-ZONE-*` neighbourhood overlays in the signed bundle.
`EXT-MIG-*`  migration nights.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from vdl7.bench import Bench
from vdl7.clock import (_dst_bounds, local_hour, night_bounds, parse_local, parse_posix_tz, posix_tz_from_iana,
                        to_local)
from vdl7.controller import Mode, VDL7Controller
from vdl7.events import EventKind
from vdl7.profiles import DEFAULT_PROFILES, Phase, RoadClass, default_bundle, validate_bundle
from vdl7.sites import SITES, site

UTC = timezone.utc


# ================================================================ CLOCK
def _all_zones():
    zoneinfo = pytest.importorskip("zoneinfo")
    zones = sorted(zoneinfo.available_timezones())
    if not zones:
        pytest.skip("no IANA database on this host")
    return zoneinfo, zones


def test_EXT_CLK_4_rule_engine_matches_iana_for_every_zone_on_earth():
    """For every IANA zone, the POSIX rule the database compiles for it,
    run through the firmware's rule engine, gives the same UTC offset as
    `zoneinfo` mid-month and one second either side of every transition,
    2027-2030."""
    zoneinfo, zones = _all_zones()
    checked, mismatches = 0, []
    for name in zones:
        try:
            rule = posix_tz_from_iana(name)
        except LookupError:
            continue                                     # a link or TZif v1 file without a footer
        tz, zi = parse_posix_tz(rule), zoneinfo.ZoneInfo(name)
        pts = [datetime(y, m, 15, 12, tzinfo=UTC) for y in range(2027, 2031) for m in range(1, 13)]
        if tz.has_dst:
            for y in range(2027, 2031):
                for t in _dst_bounds(tz, y):
                    pts += [t - timedelta(seconds=1), t, t + timedelta(seconds=1)]
        for t in pts:
            if tz.utcoffset_s(t) != int(t.astimezone(zi).utcoffset().total_seconds()):
                mismatches.append((name, rule, t.isoformat()))
                break
        checked += 1
    assert checked > 300 and not mismatches, mismatches[:5]


@pytest.mark.parametrize("key", sorted(SITES))
def test_EXT_CLK_4b_every_site_preset_matches_its_iana_zone(key):
    """Each preset's compiled-in rule matches its zone every 6 h, 2024-2030."""
    zoneinfo = pytest.importorskip("zoneinfo")
    s = SITES[key]
    try:
        zi = zoneinfo.ZoneInfo(s.iana)
    except Exception:
        pytest.skip(f"{s.iana} not available")
    tz = parse_posix_tz(s.tz)
    t, end = datetime(2024, 1, 1, tzinfo=UTC), datetime(2031, 1, 1, tzinfo=UTC)
    while t < end:
        assert tz.utcoffset_s(t) == t.astimezone(zi).utcoffset().total_seconds(), (key, t)
        t += timedelta(hours=6)


@pytest.mark.parametrize("rule, utc, offset_h", [
    ("EST5EDT", "2026-07-01T12:00", -4),                          # no rules: US default, as glibc
    ("EST5EDT", "2026-01-01T12:00", -5),
    ("<+0330>-3:30", "2026-07-01T12:00", 3.5),                    # quoted name, half-hour, no DST
    ("ACST-9:30ACDT,M10.1.0,M4.1.0/3", "2026-01-15T00:00", 10.5), # southern summer
    ("ACST-9:30ACDT,M10.1.0,M4.1.0/3", "2026-07-15T00:00", 9.5),
    ("IST-1GMT0,M10.5.0,M3.5.0/1", "2026-07-01T12:00", 1),        # Dublin's negative DST form
    ("IST-1GMT0,M10.5.0,M3.5.0/1", "2026-01-01T12:00", 0),
    ("EST5EDT,J60/2,J300/2", "2028-03-01T12:00", -4),             # Jn never counts Feb 29: Mar 1
    ("EST5EDT,J60/2,J300/2", "2028-02-29T12:00", -5),
    ("EST5EDT,59/2,300/2", "2028-02-29T12:00", -4),               # n counts it: day 59 is Feb 29
    ("EST5EDT,0/0,J365/25", "2026-12-31T23:00", -4),              # permanent DST, RFC 8536 idiom
    ("EST5EDT,0/0,J365/25", "2026-06-15T12:00", -4),
    ("<-04>4<-03>,M9.1.6/24,M4.1.6/24", "2026-09-06T03:59:59", -4),   # Sat 24:00 = Sun 00:00 local
    ("<-04>4<-03>,M9.1.6/24,M4.1.6/24", "2026-09-06T04:00:00", -3),
])
def test_EXT_CLK_5_posix_rule_forms(rule, utc, offset_h):
    t = datetime.fromisoformat(utc).replace(tzinfo=UTC)
    assert parse_posix_tz(rule).utcoffset_s(t) == offset_h * 3600


@pytest.mark.parametrize("bad", ["", "EST", "5EST", "EST5EDT,M13.1.0,M11.1.0", "EST5EDT,M3.6.0,M11.1.0",
                                 "EST5EDT,M3.2.7,M11.1.0", "EST5EDT,J0,J300", "EST5EDT,M3.2.0", "EST168",
                                 "EST55EDT",                                # a typo for EST5EDT: 55 h is no offset
                                 "EST5EDT,M3.2.0/,M11.1.0", "EST5EDT,M3.2.0/2:00:00:99,M11.1.0"])
def test_EXT_CLK_5b_bad_rules_are_refused_at_commissioning(bad):
    with pytest.raises(ValueError):
        parse_posix_tz(bad)
    b = Bench(RoadClass.LOCAL)
    with pytest.raises(ValueError):
        VDL7Controller(replace(b.cfg, tz=bad), b.flash, b.rtc, b.verifier)


def test_EXT_CLK_5c_local_to_utc_is_fold_0_even_for_negative_dst():
    """Dublin's rule puts 'daylight' time in winter (IST-1GMT0). The
    repeated hour still resolves to its first instant and the skipped hour
    lands after the gap, as zoneinfo does with fold=0."""
    dublin = parse_posix_tz("IST-1GMT0,M10.5.0,M3.5.0/1")
    assert dublin.to_utc(datetime(2027, 10, 31, 1, 30)) == datetime(2027, 10, 31, 0, 30, tzinfo=UTC)
    assert dublin.to_utc(datetime(2027, 3, 28, 1, 30)) == datetime(2027, 3, 28, 1, 30, tzinfo=UTC)
    dc = parse_posix_tz(SITES["dc"].tz)
    assert dc.to_utc(datetime(2026, 11, 1, 1, 30)) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)    # EDT first
    assert dc.to_utc(datetime(2026, 3, 8, 2, 30)) == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)      # 03:30 EDT


def test_EXT_CLK_5d_a_rule_that_misses_the_zones_own_transitions_is_refused():
    """A TZif footer only governs after the file's last explicit transition.
    Gaza's and Hebron's list Ramadan-related changes the recurring rule
    misses, so commissioning from the rule is refused; zones whose explicit
    transitions the rule reproduces (New York, to 2037) pass."""
    zoneinfo, zones = _all_zones()
    since = datetime(2027, 1, 1, tzinfo=UTC)
    assert posix_tz_from_iana("America/New_York", since) == "EST5EDT,M3.2.0,M11.1.0"
    for name in ("Asia/Gaza", "Asia/Hebron", "Africa/Casablanca"):
        if name not in zones:
            continue
        try:
            rule = posix_tz_from_iana(name, since)
        except LookupError as e:
            assert "disagrees" in str(e) or "footer" in str(e)
            continue
        tz, zi = parse_posix_tz(rule), zoneinfo.ZoneInfo(name)       # accepted: then it must be right
        t = since
        while t.year < 2031:
            assert tz.utcoffset_s(t) == int(t.astimezone(zi).utcoffset().total_seconds()), (name, t)
            t += timedelta(hours=6)


def test_EXT_CLK_6_dc_rule_is_what_iana_compiles():
    try:
        assert posix_tz_from_iana("America/New_York") == SITES["dc"].tz
    except LookupError:
        pytest.skip("no IANA database on this host")


@pytest.mark.parametrize("key, start, curfew_utc_hour", [
    ("sydney", "2026-01-15 19:00", 12),      # AEDT, UTC+11: 23:00 local is 12:00 UTC
    ("sydney", "2026-07-15 17:00", 13),      # AEST, UTC+10
    ("adelaide", "2026-01-15 20:00", 12),    # ACDT, UTC+10:30: 23:00 local is 12:30 UTC
    ("paris", "2026-10-13 19:00", 21),       # CEST
    ("tucson", "2026-10-13 19:00", 6),       # MST all year
])
def test_EXT_CLK_7_curfew_lands_at_2300_local_anywhere(key, start, curfew_utc_hour):
    b = Bench(RoadClass.LOCAL, start=start, site=site(key))
    b.keep_history = True
    day = start[:10]
    b.run_until(f"{day} 23:05", dt=10)
    first = next(o for o in b.outputs if o.phase == Phase.CURFEW)
    t0 = parse_local(start, b.site.tz)
    landed = t0 + timedelta(seconds=first.mono)
    assert landed.hour == curfew_utc_hour and abs(local_hour(landed, b.site.tz) - 23.0) < 0.01
    assert b.node.output.level == DEFAULT_PROFILES[RoadClass.LOCAL].base(Phase.CURFEW)


def test_EXT_CLK_8_polar_night_lights_all_day_at_the_evening_level():
    """Tromso at the winter solstice: the sun never climbs above -3 deg, so
    the street is lit all day on the astronomical clock (the morning at the
    dawn level, from noon the evening level), and the node does not try to
    learn a night that has no dusk."""
    b = Bench(RoadClass.LOCAL, start="2026-12-21 06:00", site=site("tromso"))
    seed = b.flash.checkpoint.learned_midpoint_h
    out = b.run_until("2026-12-21 09:00", dt=30)
    assert out.lit and out.phase == Phase.DAWN and out.level == 50
    out = b.run_until("2026-12-21 12:30", dt=30)
    assert out.lit and out.phase == Phase.EVENING and out.level == 80 and "PHOTOCELL_EARLY" not in out.reasons
    out = b.run_until("2026-12-22 06:00", dt=30)
    assert out.lit and out.phase == Phase.DAWN
    assert b.flash.checkpoint.learned_midpoint_h == seed and not b.flash.checkpoint.learned


def test_EXT_CLK_9_midnight_sun_and_white_nights():
    """Tromso in June: never dark, never lit. Reykjavik in June: the sun
    stays above -3 deg, so only the photocell can light the street, and a
    photocell dusk at midnight is not learned as a night."""
    t = Bench(RoadClass.LOCAL, start="2026-06-21 12:00", site=site("tromso"))
    t.keep_history = True
    t.run_until("2026-06-22 12:00", dt=60)
    assert not any(o.lit for o in t.outputs)
    r = Bench(RoadClass.LOCAL, start="2026-06-21 12:00", site=site("reykjavik"))
    r.keep_history = True
    r.run_until("2026-06-22 12:00", dt=30)
    lit = [o for o in r.outputs if o.lit]
    assert lit and all("PHOTOCELL_EARLY" in o.reasons for o in lit)
    assert not r.flash.checkpoint.learned
    assert "PHOTOCELL_FAULT" not in r.node.output.alarms


def test_EXT_CLK_9b_night_bounds_at_the_edges_of_polar_night():
    """Just before polar night Tromso's dusk comes before clock noon (the
    sun peaks at 11:35); searching from solar noon finds it. In polar night
    there is no dusk at all, and a white night's dusk after midnight belongs
    to the evening before."""
    t = site("tromso")
    dusk, dawn = night_bounds(t.lat, t.lon, date(2026, 12, 15), tz=t.tz)
    assert to_local(dusk, t.tz).date() == date(2026, 12, 15) and to_local(dusk, t.tz).hour == 11
    assert to_local(dawn, t.tz).date() == date(2026, 12, 16)
    assert night_bounds(t.lat, t.lon, date(2026, 12, 20), tz=t.tz) == (None, None)
    last, never = night_bounds(t.lat, t.lon, date(2026, 12, 16), tz=t.tz)
    assert last is not None and never is None                                   # polar night begins
    r = site("reykjavik")
    dusk, dawn = night_bounds(r.lat, r.lon, date(2026, 5, 28), tz=r.tz)
    assert to_local(dusk, r.tz) > datetime(2026, 5, 29, 0, 0) and to_local(dawn, r.tz) < datetime(2026, 5, 29, 4, 0)


def test_EXT_CLK_9c_learning_gate_finds_a_dusk_after_midnight():
    """The gate that keeps storm darkness from being learned as dusk
    compares a photocell switch with the sun's own dusk or dawn. A white
    night's dusk after midnight belongs to the evening before; the gate
    finds it there (such short nights are still not learned: 6 h minimum)."""
    r = Bench(RoadClass.LOCAL, start="2026-05-28 12:00", site=site("reykjavik"))
    dusk, dawn = night_bounds(r.site.lat, r.site.lon, date(2026, 5, 28), tz=r.site.tz)
    assert to_local(dusk, r.site.tz).date() == date(2026, 5, 29)
    assert r.node._near_sun_transition(dusk + timedelta(minutes=20), dusk=True)
    assert r.node._near_sun_transition(dawn - timedelta(minutes=20), dusk=False)
    assert not r.node._near_sun_transition(dusk - timedelta(hours=3), dusk=True)     # 21:00: a storm, not dusk


def test_EXT_CLK_10_safe_mode_in_the_southern_hemisphere():
    """A Sydney node learns a clocked night, loses its clock, and lands the
    curfew from its photocell alone, as DC's does."""
    s = site("sydney")
    learner = Bench(RoadClass.LOCAL, start="2026-07-12 15:00", site=s)
    learner.run_until("2026-07-13 09:00", dt=10)
    assert learner.flash.checkpoint.learned
    rtc = learner.rtc
    rtc.reset()
    b = Bench(RoadClass.LOCAL, start="2026-07-13 14:00", flash=learner.flash, rtc=rtc, online=False,
              cms=learner.cms, site=s)
    start = b.utc
    b.keep_history = True
    b.run_until("2026-07-13 23:30", dt=10)
    first = next(o for o in b.outputs if o.phase == Phase.CURFEW and o.mode == Mode.SAFE)
    landed = to_local(start + timedelta(seconds=first.mono), s.tz)
    assert abs((landed.hour * 60 + landed.minute) - 23 * 60) <= 10, landed


# ================================================================ ZONES
def _zoned_bundle(version=2):
    bd = default_bundle(version=version)
    bd.zones = {"rock-creek-buffer": {RoadClass.LOCAL: (60, 40, 30, 30, 30), RoadClass.COLLECTOR: (80, 60, 40, 40, 50)},
                "u-street-nightlife": {RoadClass.ARTERIAL: (100, 100, 90, 60, 75)}}
    return bd


def test_EXT_ZONE_1_overlay_levels_apply_and_survive_signing_and_boot():
    b = Bench(RoadClass.LOCAL, zone="rock-creek-buffer")
    assert b.deliver(b.cms.bundle(_zoned_bundle()))
    for t, lv in [("2026-10-13 21:00", 60), ("2026-10-13 22:30", 40), ("2026-10-14 00:30", 30)]:
        out = b.run_until(t, dt=5)
        assert out.level == lv and "ZONE:rock-creek-buffer" in out.reasons, t
    b.power_cut(outage_s=30)
    assert b.flash.bundle.zones["rock-creek-buffer"][RoadClass.LOCAL] == (60, 40, 30, 30, 30)
    b.node.radar_detect(b.mono)
    assert b.advance(3).level == 70                       # people still get the class boost


def test_EXT_ZONE_2_unknown_zone_and_other_classes_use_class_levels():
    b = Bench(RoadClass.ALLEY, zone="rock-creek-buffer")  # zone has no alley entry
    assert b.deliver(b.cms.bundle(_zoned_bundle()))
    out = b.run_until("2026-10-13 21:00", dt=5)
    assert out.level == 70
    c = Bench(RoadClass.LOCAL, zone="not-in-bundle")
    assert c.deliver(c.cms.bundle(_zoned_bundle()))
    out = c.run_until("2026-10-13 21:00", dt=5)
    assert out.level == 80 and not any(r.startswith("ZONE") for r in out.reasons)


def test_EXT_ZONE_3_nightlife_overlay_keeps_an_arterial_bright_later():
    b = Bench(RoadClass.ARTERIAL, zone="u-street-nightlife")
    assert b.deliver(b.cms.bundle(_zoned_bundle()))
    assert b.run_until("2026-10-13 22:30", dt=5).level == 100
    assert b.run_until("2026-10-13 23:30", dt=5).level == 90
    assert b.run_until("2026-10-14 02:00", dt=5).level == 60


@pytest.mark.parametrize("zones, why", [
    ({"dark": {RoadClass.LOCAL: (60, 40, 20, 20, 20)}}, "below floor 30"),  # local floor is 30
    ({"dark": {RoadClass.ALLEY: (60, 40, 30, 20, 120)}}, "above 100"),
    ({f"z{i}": {} for i in range(40)}, "zones"),
    ({"": {}}, "zone name"),
    ({"\U0001f600" * 32: {}}, "zone name"),                 # 128 bytes in UTF-8: not the MCU's 32-byte field
    ({"rock\x00creek": {}}, "zone name"),
    ({"x" * 33: {}}, "zone name"),
])
def test_EXT_ZONE_4_unsafe_overlays_are_refused(zones, why):
    bd = default_bundle(version=2)
    bd.zones = zones
    assert any(why in e for e in validate_bundle(bd))
    b = Bench(RoadClass.LOCAL, zone="dark")
    assert not b.deliver(b.cms.bundle(bd))
    assert b.flash.version == 1


def test_EXT_ZONE_4b_bundle_numbers_that_cannot_be_integers_are_refused_not_fatal():
    """A signed bundle with Infinity or 1e400 in a level, or an issue date
    whose expiry overflows the calendar, is refused like any other bad
    bundle: the node keeps its bank and does not crash, now or at boot."""
    b = Bench(RoadClass.LOCAL)
    for patch in ({"zones": {"z": {"local": [80, 60, float("inf"), 30, 50]}}},
                  {"valid_days": float("nan")}, {"issued": "9999-12-31"}):
        d = default_bundle(version=2).to_dict()
        d.update(patch)
        assert not b.deliver(b.cms.signer.sign_obj(d))
        assert b.flash.version == 1 and "REJECT" in b.flash.install_log[-1]
    b.power_cut(outage_s=5)
    assert b.flash.version == 1 and b.run_until("2026-10-13 21:00", dt=10).level == 80


def test_EXT_ZONE_4c_zone_reason_only_where_the_zone_sets_this_class():
    b = Bench(RoadClass.ALLEY, zone="rock-creek-buffer")  # the zone has no alley entry
    assert b.deliver(b.cms.bundle(_zoned_bundle()))
    out = b.run_until("2026-10-13 21:00", dt=5)
    assert out.level == 70 and not any(r.startswith("ZONE") for r in out.reasons)


def test_EXT_ZONE_5_hin_floor_still_wins_inside_a_dark_zone():
    b = Bench(RoadClass.LOCAL, zone="rock-creek-buffer", hin=True)
    assert b.deliver(b.cms.bundle(_zoned_bundle()))
    out = b.run_until("2026-10-14 02:00", dt=5)
    assert out.level == 60 and "FLOOR_HIN" in out.reasons


# ============================================================ MIGRATION
def test_EXT_MIG_1_migration_night_holds_presence_classes_at_their_2200_level():
    """A forecast heavy-migration night: local streets hold 60 % instead of
    80 % from dusk; a pedestrian still gets 70 %; the event expires on its
    TTL; arterials are untouched."""
    b = Bench(RoadClass.LOCAL, start="2026-10-13 17:00")
    b.run_until("2026-10-13 18:00", dt=10)
    b.send(EventKind.MIGRATION, ttl_s=4 * 3600, payload={"source": "BirdCast", "level": "high"})
    out = b.run_until("2026-10-13 20:00", dt=5)
    assert out.level == 60 and "MIGRATION" in out.reasons
    b.node.radar_detect(b.mono)
    assert b.advance(3).level == 70
    out = b.run_until("2026-10-13 22:30", dt=5)          # TTL over at 22:00 anyway; step phase
    assert out.level == 60 and "MIGRATION" not in out.reasons
    a = Bench(RoadClass.ARTERIAL, start="2026-10-13 17:00")
    a.run_until("2026-10-13 18:00", dt=10)
    a.send(EventKind.MIGRATION, ttl_s=4 * 3600)
    out = a.run_until("2026-10-13 20:00", dt=5)
    assert out.level == 100 and "MIGRATION" not in out.reasons


def test_EXT_MIG_2_migration_never_beats_floors_emergencies_or_storm_darkness():
    b = Bench(RoadClass.PARK, hin=True)
    b.run_until("2026-10-13 19:30", dt=10)
    b.send(EventKind.MIGRATION, ttl_s=6 * 3600)
    assert b.advance(120, dt=5).level == 60               # park evening 60 -> step 40, HIN floor 60
    b.send(EventKind.EMERGENCY, ttl_s=600)
    assert b.advance(5).level == 100
    # a forecast sent in the afternoon is live during a 14:30 thunderstorm:
    # storm darkness with the sun up still gets the evening level (R-SAF-4)
    s = Bench(RoadClass.LOCAL, start="2026-10-13 13:00")
    s.run_until("2026-10-13 13:30", dt=10)
    s.send(EventKind.MIGRATION, ttl_s=12 * 3600)
    s.lx_override = 5.0
    out = s.run_until("2026-10-13 14:30", dt=5)
    assert out.lit and out.level == 80 and "MIGRATION" not in out.reasons
    s.lx_override = None
    out = s.run_until("2026-10-13 20:00", dt=5)                   # and holds from dusk as asked
    assert out.level == 60 and "MIGRATION" in out.reasons


def test_EXT_MIG_3_migration_classes_are_signed_bundle_policy():
    bd = default_bundle(version=2)
    bd.migration_classes = (RoadClass.LOCAL, RoadClass.COLLECTOR)
    b = Bench(RoadClass.COLLECTOR, start="2026-10-13 17:00")
    assert b.deliver(b.cms.bundle(bd))
    b.run_until("2026-10-13 18:00", dt=10)
    b.send(EventKind.MIGRATION, ttl_s=4 * 3600)
    out = b.run_until("2026-10-13 20:00", dt=5)
    assert out.level == 70 and "MIGRATION" in out.reasons
    bad = default_bundle(version=3)
    bad.migration_classes = (RoadClass.LOCAL, RoadClass.LOCAL)
    assert validate_bundle(bad)
