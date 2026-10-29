"""Tonight's sky in DC Tonight: when the night is dark, what the Moon does, and
how much of each owner's window falls in the dark.

The reference times are the U.S. Naval Observatory's 2026 tables for
Washington, DC (W077 02, N38 54; aa.usno.navy.mil, "Table of Sunrise/Sunset,
Moonrise/Moonset, or Twilight Times for an Entire Year", retrieved
2026-10-29), printed in EST and shifted an hour where daylight time applies.
The tables round to the minute; the tolerance is two minutes.
"""
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from vdl7.clock import DC_LAT, DC_LON, solar_elevation_exact
from vdl7.observe import dark, moon
from vdl7.tonight import TZ, _moon_path, example_project, night_sky, plan, sky_html

UTC = timezone.utc


def local(day, clock, next_morning=False):
    h, m = map(int, clock.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=TZ) + timedelta(days=next_morning)


def near(iso, expected, minutes=2):
    return abs((datetime.fromisoformat(iso) - expected).total_seconds()) <= minutes * 60


# night, sunset, astronomical dusk, astronomical dawn (next morning), sunrise (next morning), local time
USNO_SUN = [
    ("2026-10-15", "18:30", "19:58", "05:50", "07:19"),
    ("2026-12-21", "16:50", "18:25", "05:48", "07:24"),
    ("2026-06-21", "20:37", "22:36", "03:44", "05:43"),
    ("2026-10-31", "18:09", "19:39", "05:05", "06:35"),   # clocks fall back at 02:00
    ("2026-03-07", "18:07", "19:36", "06:02", "07:30"),   # clocks spring forward at 02:00
]


@pytest.mark.parametrize("night,sunset,dusk,dawn,sunrise", USNO_SUN)
def test_sunset_darkness_and_sunrise_match_the_naval_observatory(night, sunset, dusk, dawn, sunrise):
    day = date.fromisoformat(night)
    s = night_sky(day)
    assert near(s["sunset"], local(day, sunset)) and near(s["sunrise"], local(day, sunrise, True))
    assert near(s["dark"]["start"], local(day, dusk)) and near(s["dark"]["end"], local(day, dawn, True))
    assert s["headline"] == f"Dark from {s['dark']['start'][11:16]} to {s['dark']['end'][11:16]}."
    kinds = [b["kind"] for b in s["bands"]]
    assert kinds == ["civil", "nautical", "astronomical", "dark", "astronomical", "nautical", "civil"]
    edges = [s["sunset"]] + [b["end"] for b in s["bands"]]
    assert all(datetime.fromisoformat(a) < datetime.fromisoformat(b) for a, b in zip(edges, edges[1:]))
    assert edges[-1] == s["sunrise"] and s["bands"][3]["start"] == s["dark"]["start"]


@pytest.mark.parametrize("night,verb,clock,next_morning", [
    ("2026-10-15", "sets", "21:22", False),
    ("2026-10-31", "rises", "23:17", False),
    ("2026-12-21", "sets", "05:58", True),
    ("2026-06-21", "sets", "01:04", True),
    ("2026-03-07", "rises", "22:46", False),
])
def test_moonrise_and_moonset_match_the_naval_observatory(night, verb, clock, next_morning):
    day = date.fromisoformat(night)
    m = night_sky(day)["moon"]
    h, mm = map(int, re.search(rf"{verb} at (\d\d):(\d\d)", m["summary"]).groups())
    expected = local(day, clock, next_morning)
    assert abs(h * 60 + mm - (expected.hour * 60 + expected.minute)) <= 2
    edge = m["up"][-1]["end"] if verb == "sets" else m["up"][0]["start"]
    assert near(edge, expected)


def test_a_new_moon_and_a_full_moon_night():
    new = night_sky(date(2026, 11, 9))        # USNO: sets 16:51 before the 16:59 sunset, rises 08:17 after sunrise
    assert new["moon"]["up"] == [] and new["moon"]["summary"] == "A new Moon, 1% lit, stays below the horizon all night."
    assert new["moonless_dark"] == [{"start": new["dark"]["start"], "end": new["dark"]["end"]}]
    assert new["moonless_summary"] == "All of it moonless."
    full = night_sky(date(2026, 11, 24))      # USNO: rises 16:35 before the 16:49 sunset, sets 08:27 after sunrise
    assert full["moon"]["summary"] == "A full Moon, 99% lit, is up all night."
    assert full["moon"]["up"] == [{"start": full["sunset"], "end": full["sunrise"]}]
    assert full["moonless_dark"] == [] and full["moonless_summary"] == "No moonless darkness."
    assert full["moonless_dark_minutes"] == 0 and new["moonless_dark_minutes"] == new["dark"]["minutes"]


def test_the_moon_band_starts_at_moonrise_even_before_sunset():
    """The chart opens at 16:00 on the full-Moon night, but the Moon rises at
    16:35: the band must not claim the half hour before it was up."""
    page = sky_html(night_sky(date(2026, 11, 24)))                # 16:00 to 08:00, sixteen hours
    band = re.search(r'sky-moonup".*?</div>', page).group(0)
    (left, width), = [tuple(map(float, x)) for x in re.findall(r"left:([\d.]+)%;width:([\d.]+)%", band)]
    assert left == pytest.approx(100 * 35 / 960, abs=100 * 2 / 960)   # 16:35, within the tables' two minutes
    assert left + width == pytest.approx(100, abs=0.01)           # still up when the chart ends at 08:00 (sets 08:27)


@pytest.mark.parametrize("night", ["2026-10-15", "2026-10-31", "2026-06-21", "2026-03-07"])
def test_moonless_darkness_is_what_the_sky_meter_filter_keeps(night):
    """Readings every five minutes through the night: observe.dark() keeps
    exactly the ones inside the moonless intervals (a minute of rounding at
    each edge aside)."""
    s = night_sky(date.fromisoformat(night))
    spans = [(datetime.fromisoformat(x["start"]), datetime.fromisoformat(x["end"])) for x in s["moonless_dark"]]
    start, end = datetime.fromisoformat(s["sunset"]).astimezone(UTC), datetime.fromisoformat(s["sunrise"]).astimezone(UTC)
    readings = [(start + timedelta(minutes=5 * n), 18.0) for n in range(int((end - start).total_seconds() // 300))]
    kept = {t for t, _ in dark(readings, DC_LAT, DC_LON)}
    for t, _ in readings:
        if any(abs((t - edge).total_seconds()) <= 60 for span in spans for edge in span):
            continue
        assert (t in kept) == any(a <= t <= b for a, b in spans), t
    for t in kept:
        assert solar_elevation_exact(DC_LAT, DC_LON, t) < -18 and moon(t, DC_LAT, DC_LON).alt_deg < -5


def test_moon_phase_words_and_light():
    s = night_sky(date(2026, 10, 15))
    middle = datetime.fromisoformat(s["moon"]["at"]).astimezone(UTC)
    assert s["moon"]["illuminated"] == pytest.approx(moon(middle, DC_LAT, DC_LON).illuminated, abs=0.001)
    assert s["moon"]["waxing"] and s["moon"]["phase"] == "waxing crescent"       # USNO: first quarter on Oct 18
    assert s["moon"]["summary"] == "A waxing crescent, 28% lit, sets at 21:23."
    assert night_sky(date(2026, 10, 31))["moon"]["phase"] == "waning gibbous"      # full on Oct 26


def window(p, aid):
    return next(w for w in plan(p)["sky"]["windows"] if w["action_id"] == aid)


def test_each_owner_ready_window_counts_only_its_dark_minutes():
    p = example_project("2026-10-15")                            # dark 19:58-05:50, moonless from 21:50
    assert [w["action_id"] for w in plan(p)["sky"]["windows"]] == ["facade", "windows"]   # pending and requests excluded
    w = window(p, "facade")
    assert (w["dark_minutes"], w["moonless_dark_minutes"]) == (470, 470)
    assert w["summary"] == "Covers 7 h 50 min of darkness, all of it moonless."
    p["actions"][0].update(start="18:00", end="21:00")
    w = window(p, "facade")
    assert (w["dark_minutes"], w["moonless_dark_minutes"]) == (62, 0)
    assert w["summary"] == "Covers 1 h 2 min of darkness, none of it moonless."
    p["actions"][0].update(start="05:55", end="06:30")             # before noon: the following morning
    assert window(p, "facade")["summary"] == "None of this window falls in darkness."
    p["actions"][0].update(start="23:00", end="01:00")
    assert window(p, "facade")["dark_minutes"] == 120


def test_a_window_across_the_fall_back_hour_counts_real_minutes():
    p = example_project("2026-10-31")                             # 22:00 EDT to 06:00 EST: nine elapsed hours
    w = window(p, "facade")
    assert plan(p)["actions"][0]["hours"] == 9
    assert w["dark_minutes"] == 8 * 60 + 5                         # until 05:05 EST
    assert w["moonless_dark_minutes"] == 50                        # until 22:50, as the Moon nears rising
    assert w["summary"] == "Covers 8 h 5 min of darkness, 50 min of it moonless."


def test_the_sky_stays_outside_the_plan_fingerprint():
    """Receipts already in people's hands keep matching: the checked-in
    example's fingerprint is the one its receipts.csv carries."""
    p = plan(example_project("2026-10-15"))
    assert p["plan_sha256"] == "940504aee94b70e08834fb7303acb1c8a521acbd35cc16067c759ede30ed10a6"
    assert all("dark_minutes" not in a for a in p["actions"])


def test_the_fragment_is_escaped_and_drawn_on_one_time_axis():
    p = example_project("2026-10-15")
    p["actions"][0]["label"] = '<script>alert("x")</script>'
    s = plan(p)["sky"]
    page = sky_html(s)
    assert "<script>" not in page and "&lt;script&gt;" in page
    strip = re.search(r'sky-strip".*?</div>', page).group(0)
    widths = [float(w) for w in re.findall(r"width:([\d.]+)%", strip)]
    assert sum(widths) == pytest.approx(100, abs=0.05)
    assert re.findall(r'<span style="left:[\d.]+%">(\d\d:\d\d)</span>', page) == ["20:00", "22:00", "00:00", "02:00", "04:00", "06:00"]
    # 18:00 to 08:00 is fourteen hours: the 22:00-06:00 window starts 4/14 of the way along and lasts 8/14.
    assert 'style="left:28.57%;width:57.14%"' in page
    assert "Dark from 19:58 to 05:50." in page and s["claim"] in page


def test_the_action_sheet_carries_the_night():
    from vdl7.tonight import render
    page = render(plan(example_project("2026-10-15")))
    assert page.count('class="sky"') == 1 and "The night of Thursday, October 15" in page
    assert page.count("<b>Night:</b> Covers 7 h 50 min of darkness, all of it moonless.") == 2   # the two owner-ready cards
    assert "print-color-adjust:exact" in page and "Less spill" in page


@pytest.mark.parametrize("lit,waxing,limb,rx,terminator", [
    (0.28, True, 1, 4.4, 0), (0.88, False, 0, 7.6, 0), (0.5, True, 1, 0, 1), (0.12, False, 0, 7.6, 1), (0.75, True, 1, 5, 1)])
def test_the_moon_glyph_lights_the_correct_limb(lit, waxing, limb, rx, terminator):
    """Seen from the north the waxing Moon is lit on the right: the limb arc
    sweeps clockwise from the top. The terminator is half an ellipse that
    bulges toward the lit limb for a crescent and away from it when gibbous."""
    d = _moon_path(lit, waxing)
    arcs = re.findall(r"A([\d.]+) 10 0 0 (\d) 0 (-?\d+)", d)
    assert arcs[0] == ("10", str(limb), "10") and float(arcs[1][0]) == pytest.approx(rx, abs=0.01)
    assert arcs[1][1:] == (str(terminator), "-10")
