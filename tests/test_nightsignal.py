"""The Night Signal: the public curfew clock for every light in the city.

`EXT-SIG-*` check the phase times through DST and in other cities, the
signature, what subscribers are told to do, the calendar feed, and that a
migration alert reaches the streetlights as signed firmware events.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from vdl7.bench import Bench
from vdl7.clock import night_bounds
from vdl7.cms import Cms
import pytest

from vdl7.nightsignal import (CATEGORIES, dark_window, decide, migration_events, migration_season, phase_at, sign,
                              signal, to_ics, verify)
from vdl7.profiles import RoadClass
from vdl7.sites import site

UTC = timezone.utc
ISSUED = datetime(2026, 10, 14, 20, 0, tzinfo=UTC)


def at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def test_EXT_SIG_1_phase_times_are_the_nodes_own():
    doc = signal(date(2026, 10, 14), issued=ISSUED)
    assert doc["curfew"] == "2026-10-15T03:00:00Z"                       # 23:00 EDT
    starts = {p["phase"]: p["start"] for p in doc["phases"]}
    assert starts["step"] == "2026-10-15T02:00:00Z" and starts["deep"] == "2026-10-15T05:00:00Z"
    dusk, dawn = night_bounds(38.8977, -77.0365, date(2026, 10, 14))
    assert starts["evening"] == dusk.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert doc["sun"]["astronomical_dusk"] > doc["sun"]["dusk"]
    assert phase_at(doc, at("2026-10-15T03:30")) == "curfew" and phase_at(doc, at("2026-10-14T18:00")) is None


def test_EXT_SIG_2_the_fall_back_night_and_other_cities():
    """31 Oct - 1 Nov 2026: the curfew is 23:00 EDT, the dawn phase 05:00
    EST, an hour later in UTC than the night before."""
    doc = signal(date(2026, 10, 31), issued=ISSUED)
    starts = {p["phase"]: p["start"] for p in doc["phases"]}
    assert doc["curfew"] == "2026-11-01T03:00:00Z" and starts["dawn"] == "2026-11-01T10:00:00Z"
    syd = signal(date(2027, 1, 15), site=site("sydney"), issued=ISSUED)
    assert syd["curfew"] == "2027-01-15T12:00:00Z"                       # 23:00 AEDT


def test_EXT_SIG_3_signed_and_tamper_evident():
    cms = Cms()
    pub = sign(signal(date(2026, 10, 14), issued=ISSUED), cms.signer)
    doc = verify(pub, cms.verifier)
    assert doc and doc["night_of"] == "2026-10-14"
    forged = dict(pub, payload=pub["payload"].replace('"facade"', '"facadx"'))
    assert verify(forged, cms.verifier) is None
    assert verify(pub, Cms().verifier) is None
    assert verify({"payload": 3}, cms.verifier) is None


def test_EXT_SIG_4_what_each_kind_of_light_is_told():
    doc = signal(date(2026, 10, 14), issued=ISSUED)
    assert decide(doc, "facade", at("2026-10-15T01:30"))[0] == 1.0        # 21:30, evening
    assert decide(doc, "facade", at("2026-10-15T03:30"))[0] == 0.0        # 23:30, curfew
    assert decide(doc, "signage", at("2026-10-15T03:30"), open_now=True) == (0.3, "curfew phase, open")
    assert decide(doc, "parking", at("2026-10-15T06:00"))[0] == 0.5
    assert decide(doc, "parking", at("2026-10-15T06:00"), motion=True) == (1.0, "motion")
    assert decide(doc, "security", at("2026-10-15T06:00"))[0] == 0.0
    assert decide(doc, "facade", at("2026-10-14T17:00")) == (None, "daylight")
    mig = signal(date(2026, 10, 14), migration={"source": "BirdCast", "intensity": "high"}, issued=ISSUED)
    assert decide(mig, "office_interior", at("2026-10-15T00:00")) == (0.0, "evening phase, migration night")
    assert decide(mig, "signage", at("2026-10-15T00:00"))[0] == 0.5
    assert decide(mig, "parking", at("2026-10-15T00:00"))[0] == 1.0       # migration leaves car parks alone
    assert set(CATEGORIES) <= set(doc["categories"])


def test_EXT_SIG_5_calendar_feed():
    docs = [signal(date(2026, 10, 12) + timedelta(days=i), issued=ISSUED,
                   migration={"source": "BirdCast"} if i == 1 else None) for i in range(3)]
    ics = to_ics(docs)
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 4 and ics.count("Lights Out") == 1
    assert "DTSTART:20261014T030000Z" in ics and "UID:2026-10-13-migration@nocturne" in ics
    assert all(len(line) <= 75 for line in ics.split("\r\n"))
    assert "SUMMARY:Lighting curfew: facades\\, signs and empty floors off" in ics      # RFC 5545 TEXT escaping
    undated = dict(docs[0], issued=None)
    assert "DTSTAMP:\r\n" not in to_ics([undated]) and "DTSTAMP:2" in to_ics([undated])
    with pytest.raises(ValueError):
        to_ics([])


def test_EXT_SIG_6_migration_alert_reaches_the_streetlights():
    b = Bench(RoadClass.LOCAL, start="2026-10-14 17:00")
    b.run_until("2026-10-14 18:00", dt=10)
    doc = signal(date(2026, 10, 14), migration={"source": "BirdCast", "intensity": "high"}, issued=b.utc)
    (msg,) = migration_events(b.cms, [b.cfg.segment_id], doc, b.utc)
    assert b.deliver(msg)
    out = b.run_until("2026-10-14 20:00", dt=5)
    assert out.level == 60 and "MIGRATION" in out.reasons
    assert migration_events(b.cms, ["x"], signal(date(2026, 10, 14), issued=b.utc), b.utc) == []
    # sent two days early it would expire before its night; after dawn it is too late
    early = signal(date(2026, 10, 16), migration={"source": "BirdCast"}, issued=ISSUED)
    assert migration_events(b.cms, ["x"], early, ISSUED) == []
    assert len(migration_events(b.cms, ["x"], early, ISSUED + timedelta(days=1, hours=20))) == 1
    assert migration_events(b.cms, ["x"], doc, b.utc + timedelta(days=1)) == []


def test_EXT_SIG_7_migration_seasons():
    assert migration_season(date(2026, 4, 20)) and migration_season(date(2026, 10, 1))
    assert not migration_season(date(2026, 7, 1)) and not migration_season(date(2026, 12, 25))


def test_EXT_SIG_8_polar_night_and_the_midnight_sun():
    """Tromso, 20 December: the sun never reaches -3 deg, so the signal runs
    from local noon to noon and the curfew holds at 23:30. On the night
    polar night begins the dark runs on to the next noon, and on the night
    it ends it stops when the sun returns. Under the midnight sun there is
    no dark window, but the calendar still carries the curfew (05:00 end),
    so a summer feed is never an empty calendar."""
    t = site("tromso")
    doc = signal(date(2026, 12, 20), site=t, issued=ISSUED)
    assert doc["dark"]["polar_night"] and doc["sun"]["dusk"] is None
    assert doc["dark"]["from"] == "2026-12-20T11:00:00Z" and doc["dark"]["to"] == "2026-12-21T11:00:00Z"
    assert decide(doc, "facade", at("2026-12-20T22:30")) == (0.0, "curfew phase")
    assert decide(doc, "facade", at("2026-12-20T13:00"))[0] == 1.0
    begins = signal(date(2026, 12, 16), site=t, issued=ISSUED)
    assert begins["sun"]["dawn"] is None and begins["dark"]["to"] == "2026-12-17T11:00:00Z"
    start, end, polar = dark_window(t, date(2026, 12, 26))
    assert polar and end < datetime(2026, 12, 27, 11, 0, tzinfo=UTC)               # the sun is back before noon
    summer = [signal(date(2026, 6, 20) + timedelta(days=i), site=t, issued=ISSUED) for i in range(3)]
    assert all(phase_at(d, at("2026-06-20T23:00")) is None for d in summer)
    ics = to_ics(summer)
    assert ics.count("BEGIN:VEVENT") == 3 and "DTEND:20260621T030000Z" in ics
    for d in (date(2026, 12, 14), date(2026, 12, 20), date(2026, 12, 27)):          # nights join up
        assert dark_window(t, d)[1] <= dark_window(t, d + timedelta(days=1))[0]
