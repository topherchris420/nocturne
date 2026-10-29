"""DC Tonight: reversible owner actions, handoffs, and honest completion records.

No light-control interface. No citywide effect inferred from circuit-hours.
The CLI and local browser share this module; all examples are fictional.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
import re
import shutil
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from .clock import DC_LAT, DC_LON, SUNRISE_ELEVATION_DEG, night_bounds
from .nightsignal import _ics_fold, _ics_text
from .observe import DARK_MOON_DEG, DARK_SUN_DEG, moon

TZ = ZoneInfo("America/New_York")
UTC = timezone.utc
SCHEMA = "nocturne-tonight/1"
SOURCES = [
    {"title": "DC street and alley light repair", "url": "https://ddot.dc.gov/service/street-and-alley-light-repair"},
    {"title": "Lights Out DC campaign", "url": "https://www.lightsoutdc.info/"},
    {"title": "City Wildlife: Lights Out DC", "url": "https://citywildlife.org/programs/lights-out-dc/"},
    {"title": "Cornell BirdCast: lights out guidance", "url": "https://birdcast.org/lights-out/"},
]
RECEIPT_FIELDS = ["plan_sha256", "action_id", "status", "started_at", "ended_at",
                  "observer", "evidence", "service_preserved", "no_rebound"]
KINDS = {"switch_off": "Switch off an unnecessary circuit", "close_blinds": "Close existing blinds",
         "report": "Prepare an owner or DC 311 request"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _text(obj, key, path, required=False):
    value = obj.get(key, "")
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 32 for c in value):
        raise ValueError(f"{path}.{key}: use a single line of text, at most 2000 characters")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{path}.{key}: required")
    return value


def _flag(obj, key, path):
    value = obj.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"{path}.{key}: use true or false, not text or a number")
    return value


def _night(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("night_of: use YYYY-MM-DD for the evening the night begins")
    try:
        day = date.fromisoformat(value)
        if not 2000 <= day.year <= 2100:
            raise ValueError()
        return day
    except ValueError:
        raise ValueError("night_of: use a valid date between 2000 and 2100") from None


def _instant(day, value, path):
    """Noon-to-noon night; reject DST gaps/repeated clock times instead of guessing."""
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError(f"{path}: use HH:MM in Washington, DC local time")
    clock = time.fromisoformat(value)
    local = datetime.combine(day + timedelta(days=clock.hour < 12), clock)
    candidates = {local.replace(tzinfo=TZ, fold=f).astimezone(UTC) for f in (0, 1)
                  if local.replace(tzinfo=TZ, fold=f).astimezone(UTC).astimezone(TZ).replace(tzinfo=None) == local}
    if len(candidates) != 1:
        raise ValueError(f"{path}: this clock time is missing or repeated at the daylight-saving change; choose another time")
    return candidates.pop()


def blank_project(night_of=None):
    return {"schema": SCHEMA, "title": "My DC night shift", "synthetic": False,
            "night_of": night_of or datetime.now(TZ).date().isoformat(), "actions": []}


def example_project(night_of=None):
    p = blank_project(night_of)
    p.update(title="Fictional DC block — replace every example before use", synthetic=True)
    base = {"location": "Fictional building, Washington DC", "owner": "Example facilities manager",
            "authority": "private", "authorized": True, "service_reviewed": True,
            "existing_control": True, "baseline_on": True, "start": "22:00", "end": "06:00",
            "preserve": "Exit signs, stairs, paths and all occupied task areas stay as commissioned.",
            "rollback": "The owner restores the previous setting immediately if useful lighting is affected.",
            "evidence": "Invented walkthrough: this dedicated decorative circuit runs all night.",
            "power_basis": "Invented measured circuit input, including driver losses."}
    p["actions"] = [
        dict(base, id="facade", circuit="example-facade", label="Decorative facade", kind="switch_off", watts=600),
        dict(base, id="windows", circuit="example-office", label="Occupied office windows", kind="close_blinds", watts=None,
             evidence="Invented walkthrough: existing blinds can contain the occupied office's light."),
        dict(base, id="sign", circuit="example-sign", label="Closed shop sign", kind="switch_off", watts=100,
             authorized=False, owner="Example shop owner — permission pending"),
        dict(base, id="street", circuit="example-pole", label="Streetlight spilling into a bedroom", kind="report",
             authority="district", authorized=False, service_reviewed=False, watts=None,
             evidence="Example only: note the real pole ID, location, time and direction of the spill.")]
    return p


# ------------------------------------------------------------ tonight's sky
# When the night is dark, and how much of each owner's window falls in it. Times only: the
# solar clock the controller runs and the lunar series vdl7.observe checks against JPL-grade
# ephemerides. Kept out of the plan fingerprint, so receipts do not depend on it.
TWILIGHT = (("civil", -6.0), ("nautical", -12.0), ("astronomical", DARK_SUN_DEG))
SKY_RULE = ("Dark means the Sun is more than 18° below the horizon; moonless adds the Moon more than 5° below it, "
            "the rule Nocturne applies to sky-meter readings.")
SKY_METHOD = (f"Computed on this computer for {DC_LAT:.3f}° N, {-DC_LON:.3f}° W with the NOAA solar position algorithm "
              "and the Astronomical Almanac's lunar series (about 0.3°), to the minute.")
SKY_CLAIM = "It describes the night, not any light: no sky brightness is measured or inferred."


def _minute(t):
    return (t + timedelta(seconds=30)).replace(second=0, microsecond=0)


def _iso(t):
    return t.astimezone(TZ).isoformat(timespec="minutes")


def _hm(t):
    return t.astimezone(TZ).strftime("%H:%M")


def _duration(minutes):
    h, m = divmod(round(minutes), 60)
    return f"{h} h {m} min" if h and m else f"{h} h" if h else f"{m} min"


def _moon_below(start, end, degrees):
    """[(from, to)] within [start, end] while the Moon's topocentric altitude is under
    `degrees`: a ten-minute scan, then each crossing bisected to the second."""
    low = lambda t: moon(t, DC_LAT, DC_LON).alt_deg < degrees
    out, t, was = [], start, low(start)
    since = start
    while t < end:
        t2 = min(t + timedelta(minutes=10), end)
        if low(t2) != was:
            lo, hi = t, t2
            for _ in range(20):
                mid = lo + (hi - lo) / 2
                lo, hi = (mid, hi) if low(mid) == was else (lo, mid)
            if was:
                out.append((since, hi))
            since, was = hi, not was
        t = t2
    if was:
        out.append((since, end))
    return [(a, b) for a, b in ((_minute(a), _minute(b)) for a, b in out) if b > a]


def _overlap(start, end, spans):
    return sum(max(0.0, (min(end, b) - max(start, a)).total_seconds()) for a, b in spans) / 60


@lru_cache(maxsize=256)
def _night_events(day):
    """Sunset, twilight, darkness and the Moon over DC for the night beginning on `day`.
    At DC's latitude every night of the year has all three twilights and a dark interval."""
    sunset, sunrise = (_minute(t) for t in night_bounds(DC_LAT, DC_LON, day, SUNRISE_ELEVATION_DEG))
    dusk, dawn = {}, {}
    for name, degrees in TWILIGHT:
        dusk[name], dawn[name] = (_minute(t) for t in night_bounds(DC_LAT, DC_LON, day, degrees))
    below = _moon_below(sunset, sunrise, SUNRISE_ELEVATION_DEG)        # rise and set: the upper limb on the horizon
    up, t = [], sunset
    for a, b in below:
        if a > t:
            up.append((t, a))
        t = b
    if t < sunrise:
        up.append((t, sunrise))
    middle = _minute(sunset + (sunrise - sunset) / 2)
    now, later = moon(middle, DC_LAT, DC_LON), moon(middle + timedelta(hours=1), DC_LAT, DC_LON)
    return {"sunset": sunset, "sunrise": sunrise, "dusk": dusk, "dawn": dawn, "up": up, "middle": middle,
            "moonless": _moon_below(dusk["astronomical"], dawn["astronomical"], DARK_MOON_DEG),
            "lit": now.illuminated, "waxing": later.elongation_deg > now.elongation_deg}


def night_sky(day, windows=()):
    """Tonight's sky for the page, the action sheet and plan.json. `windows` holds
    (action id, label, start, end) for each owner-ready action."""
    e = _night_events(day)
    dark = (e["dusk"]["astronomical"], e["dawn"]["astronomical"])
    lit, moonless = e["lit"], e["moonless"]
    phase = ("new Moon" if lit < 0.03 else "full Moon" if lit > 0.97 else
             ("waxing " if e["waxing"] else "waning ") + ("crescent" if lit < 0.5 else "gibbous"))
    events = sorted([(a, "rises") for a, _ in e["up"] if a > e["sunset"]] + [(b, "sets") for _, b in e["up"] if b < e["sunrise"]])
    when = ("stays below the horizon all night" if not e["up"] else "is up all night" if not events else
            " and ".join(f"{verb} at {_hm(t)}" for t, verb in events))
    if not moonless:
        moonless_text = "No moonless darkness."
    elif moonless == [dark]:
        moonless_text = "All of it moonless."
    else:
        moonless_text = "Moonless from " + " and from ".join(f"{_hm(a)} to {_hm(b)}" for a, b in moonless) + "."
    edges = [e["sunset"], e["dusk"]["civil"], e["dusk"]["nautical"], dark[0], dark[1], e["dawn"]["nautical"],
             e["dawn"]["civil"], e["sunrise"]]
    kinds = ["civil", "nautical", "astronomical", "dark", "astronomical", "nautical", "civil"]
    out = []
    for aid, label, start, end in windows:
        d, m = round(_overlap(start, end, [dark])), round(_overlap(start, end, moonless))
        summary = ("None of this window falls in darkness." if not d else
                   f"Covers {_duration(d)} of darkness, " + ("all of it moonless." if m == d else
                   "none of it moonless." if not m else f"{_duration(m)} of it moonless."))
        out.append({"action_id": aid, "label": label, "start": _iso(start), "end": _iso(end),
                    "dark_minutes": d, "moonless_dark_minutes": m, "summary": summary})
    return {"place": "Washington, DC", "latitude": DC_LAT, "longitude": DC_LON,
            "title": f"The night of {day:%A}, {day:%B} {day.day}",
            "sunset": _iso(e["sunset"]), "sunrise": _iso(e["sunrise"]),
            "dark": {"start": _iso(dark[0]), "end": _iso(dark[1]), "minutes": round((dark[1] - dark[0]).total_seconds() / 60)},
            "bands": [{"kind": k, "start": _iso(a), "end": _iso(b)} for k, a, b in zip(kinds, edges, edges[1:])],
            "moon": {"illuminated": round(lit, 3), "waxing": e["waxing"], "phase": phase, "at": _iso(e["middle"]),
                     "up": [{"start": _iso(a), "end": _iso(b)} for a, b in e["up"]],
                     "summary": f"A {phase}, {round(100 * lit)}% lit, {when}."},
            "moonless_dark": [{"start": _iso(a), "end": _iso(b)} for a, b in moonless],
            "moonless_dark_minutes": round(sum((b - a).total_seconds() for a, b in moonless) / 60),
            "headline": f"Dark from {_hm(dark[0])} to {_hm(dark[1])}.", "moonless_summary": moonless_text,
            "windows": out, "rule": SKY_RULE, "method": SKY_METHOD, "claim": SKY_CLAIM}


def _moon_path(lit, waxing, r=10):
    """The lit part of the disc as seen from DC: the bright limb is a semicircle, the terminator
    half an ellipse. SVG's y axis points down, so sweep flag 1 runs clockwise on screen."""
    return (f"M0 {-r}A{r} {r} 0 0 {int(waxing)} 0 {r}"
            f"A{r * abs(1 - 2 * lit):.2f} {r} 0 0 {int((lit < 0.5) != waxing)} 0 {-r}Z")


def sky_html(sky):
    """Tonight's sky as one fragment for the page and the action sheet, which style its classes:
    the Moon, the headline, a timeline from sunset to sunrise and each owner-ready window."""
    esc = lambda x: html.escape(str(x), quote=True)
    at = lambda iso: datetime.fromisoformat(iso).astimezone(UTC)
    hm = lambda iso: _hm(at(iso))
    sunset, sunrise, windows, m = at(sky["sunset"]), at(sky["sunrise"]), sky["windows"], sky["moon"]
    hour = lambda t: t.replace(minute=0, second=0, microsecond=0)       # DC's offsets are whole hours
    t0 = hour(min([sunset] + [at(w["start"]) for w in windows]) - timedelta(minutes=20))
    t1 = hour(max([sunrise] + [at(w["end"]) for w in windows]) + timedelta(minutes=20)) + timedelta(hours=1)
    pct = lambda t: 100 * (t - t0).total_seconds() / (t1 - t0).total_seconds()
    span = lambda a, b: f'style="left:{pct(a):.2f}%;width:{pct(b) - pct(a):.2f}%"'
    ticks = [t for t in (t0 + timedelta(hours=n) for n in range(int((t1 - t0).total_seconds() // 3600) + 1))
             if t.astimezone(TZ).hour % 2 == 0 and 4 < pct(t) < 96]
    bands = ([("day", t0, sunset)] + [(b["kind"], at(b["start"]), at(b["end"])) for b in sky["bands"]]
             + [("day", sunrise, t1)])
    moon_up = "".join(f'<span {span(t0 if at(u["start"]) == sunset else at(u["start"]), t1 if at(u["end"]) == sunrise else at(u["end"]))}>'
                      "Moon up</span>" for u in m["up"])
    rows = "".join(f'<div class="sky-window"><p><span><b>{esc(w["label"])}</b> · {hm(w["start"])}–{hm(w["end"])}</span><small>{esc(w["summary"])}</small></p>'
                   f'<div class="sky-track" aria-hidden="true"><span {span(at(w["start"]), at(w["end"]))}></span></div></div>'
                   for w in windows)
    return (f'<div class="sky"><p class="sky-eyebrow">{esc(sky["title"])}</p><div class="sky-head">'
            f'<svg class="sky-moon" viewBox="-11 -11 22 22" role="img" aria-label="{esc(m["summary"])}"><circle r="10"/>'
            f'<path d="{_moon_path(m["illuminated"], m["waxing"])}"/></svg><div>'
            f'<h2 class="sky-headline">{esc(sky["headline"])} <em>{esc(sky["moonless_summary"])}</em></h2>'
            f'<p class="sky-line">Sunset {hm(sky["sunset"])} · sunrise {hm(sky["sunrise"])}. {esc(m["summary"])}</p></div></div>'
            '<div class="sky-chart">' + "".join(f'<i class="sky-grid" style="left:{pct(t):.2f}%"></i>' for t in ticks)
            + f'<div class="sky-track sky-moonup" aria-hidden="true">{moon_up}</div><div class="sky-track sky-strip" aria-hidden="true">'
            + "".join(f'<i class="sky-{k}" {span(a, b)}></i>' for k, a, b in bands if b > a) + f'</div>{rows}'
            + '<div class="sky-ticks" aria-hidden="true">'
            + "".join(f'<span style="left:{pct(t):.2f}%">{_hm(t)}</span>' for t in ticks) + "</div></div>"
            f'<p class="sky-note">{esc(sky["rule"])} {esc(sky["method"])} {esc(sky["claim"])}</p></div>')


def plan(project):
    if not isinstance(project, dict) or project.get("schema") != SCHEMA:
        raise ValueError(f"project.schema: expected {SCHEMA}")
    day = _night(project.get("night_of"))
    title = _text(project, "title", "project", True)
    synthetic = _flag(project, "synthetic", "project")
    raw_actions = project.get("actions")
    if not isinstance(raw_actions, list) or len(raw_actions) > 200:
        raise ValueError("actions: provide a list of at most 200 separately controlled circuits or requests")
    actions, ids, circuits, spans = [], set(), set(), {}
    for index, raw in enumerate(raw_actions):
        path = f"actions[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: expected an object")
        a = {k: _text(raw, k, path, k in ("id", "label", "location", "kind", "authority"))
             for k in ("id", "label", "location", "kind", "authority", "owner", "circuit", "preserve",
                       "rollback", "evidence", "power_basis")}
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", a["id"]) or a["id"] in ids:
            raise ValueError(f"{path}.id: use a unique ID of 1–64 letters, digits, hyphens or underscores")
        ids.add(a["id"])
        if a["kind"] not in KINDS or a["authority"] not in ("private", "district", "federal", "unknown"):
            raise ValueError(f"{path}: unknown kind or authority")
        for key in ("authorized", "service_reviewed", "existing_control", "baseline_on"):
            a[key] = _flag(raw, key, path)
        watts = raw.get("watts")
        if watts is not None and (isinstance(watts, bool) or not isinstance(watts, (int, float))
                                  or not 0 <= watts <= 1e7 or not math.isfinite(watts)):
            raise ValueError(f"{path}.watts: use finite circuit input watts, 0–10,000,000, or null if unknown")
        a["watts"] = watts
        a["start"], a["end"] = raw.get("start", "22:00"), raw.get("end", "06:00")
        start, end = _instant(day, a["start"], f"{path}.start"), _instant(day, a["end"], f"{path}.end")
        if end <= start:
            raise ValueError(f"{path}.end: must follow start within this noon-to-noon night")
        a.update(start_at=start.astimezone(TZ).isoformat(), end_at=end.astimezone(TZ).isoformat(),
                 hours=(end - start).total_seconds() / 3600)
        spans[a["id"]] = (start, end)
        if a["kind"] != "report" and a["circuit"]:
            circuit_key = a["circuit"].casefold()
            if circuit_key in circuits:
                raise ValueError(f"{path}.circuit: already used; put a circuit in only one action to avoid double-counting")
            circuits.add(circuit_key)
        reasons = []
        if a["kind"] == "report" or a["authority"] != "private":
            a["status"] = "request_only"
            reasons.append("Send this observation to the responsible owner or operator; a request is not a completed lighting change.")
        else:
            for ok, reason in (
                (a["owner"] and a["authorized"], "Record the responsible owner and permission for this exact action."),
                (a["circuit"], "Name the separately controlled circuit or window group."),
                (a["existing_control"], "Confirm an existing switch, timer or blind; hardware purchases are a later job."),
                (a["service_reviewed"] and a["preserve"], "Review the whole window and record how required lighting and occupied use remain served."),
                (a["evidence"], "Record the walkthrough or operating record that supports the change."),
                (a["rollback"], "Record how the owner will restore the previous condition."),
                (a["kind"] != "switch_off" or a["baseline_on"], "Confirm this circuit would otherwise be on throughout the entire proposed window."),
            ):
                if not ok:
                    reasons.append(reason)
            a["status"] = "needs_owner_check" if reasons else "owner_ready"
        a["reasons"] = reasons
        a["potential_kwh"] = (watts * a["hours"] / 1000 if a["status"] == "owner_ready"
                              and a["kind"] == "switch_off" and watts is not None and a["power_basis"] else None)
        a["request_draft"] = _request(a) if a["status"] != "owner_ready" else ""
        actions.append(a)
    canonical = {"schema": SCHEMA, "title": title, "synthetic": synthetic,
                 "night_of": day.isoformat(), "actions": actions}
    ready = [a for a in actions if a["status"] == "owner_ready"]
    md = day.month, day.day
    return dict(canonical, plan_sha256=_digest(canonical), timezone="America/New_York",
                migration_season=(3, 1) <= md <= (6, 15) or (8, 15) <= md <= (11, 30),
                migration_note="Seasonal BirdCast guidance, not a live migration forecast; use dusk-to-dawn containment where practical.",
                ready_count=len(ready), request_count=sum(a["status"] == "request_only" for a in actions),
                pending_count=sum(a["status"] == "needs_owner_check" for a in actions),
                potential_kwh=sum(a["potential_kwh"] or 0 for a in ready),
                unquantified_count=sum(a["kind"] == "switch_off" and a["potential_kwh"] is None for a in ready),
                containment_hours=sum(a["hours"] for a in ready if a["kind"] == "close_blinds"),
                sky=night_sky(day, [(a["id"], a["label"], *spans[a["id"]]) for a in ready]),
                sources=SOURCES, sources_checked="2026-10-15",
                claim="Plan only. Energy is conditional on the supplied baseline and circuit power; no measured skyglow reduction.")


def _request(a):
    if a["authority"] == "district":
        route = "DC 311 / DDOT streetlight investigation: https://311.dc.gov/"
        ask = "Please investigate the light's operation, aiming and any appropriate shielding while retaining safe roadway and pedestrian lighting."
    elif a["authority"] == "federal":
        route = "The responsible federal property's facilities operator (verify from the property, not DDOT)."
        ask = "Please review an owner-approved reduction of unnecessary exterior light or containment of window spill using existing controls."
    else:
        route = a["owner"] or "Identify the property owner or facilities manager first."
        ask = "Could we review this light together and agree a reversible switch or blind change that preserves needed lighting?"
    return (f"Route: {route}\nLocation: {a['location']}\nSource: {a['label']} / {a['circuit'] or 'ID to record'}\n"
            f"Observation: {a['evidence'] or 'Add a dated observation from a lawful viewing location.'}\n"
            f"{ask}\nThis is a draft, not a submitted request. Record the reference number and actual response separately.")


def _receipt_time(value, path):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(UTC)
    except (ValueError, AttributeError):
        raise ValueError(f"{path}: use an ISO timestamp with its UTC offset") from None


def reconcile(project, receipts):
    p = plan(project)
    if not isinstance(receipts, list) or len(receipts) > 200:
        raise ValueError("receipts: expected at most 200 records")
    ready = {a["id"]: a for a in p["actions"] if a["status"] == "owner_ready"}
    seen, rows = set(), []
    for index, raw in enumerate(receipts):
        path = f"receipts[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: expected an object")
        r = {k: _text(raw, k, path) for k in RECEIPT_FIELDS}
        if r["plan_sha256"] != p["plan_sha256"]:
            raise ValueError(f"{path}: receipt belongs to another plan; keep the exact original project and date")
        aid = r["action_id"]
        if aid not in ready or aid in seen:
            raise ValueError(f"{path}.action_id: not an owner-ready action or already recorded")
        seen.add(aid)
        if r["status"] not in ("", "completed", "skipped", "rolled_back"):
            raise ValueError(f"{path}.status: use completed, skipped, rolled_back, or blank")
        if any(r[k] not in ("", "yes", "no") for k in ("service_preserved", "no_rebound")):
            raise ValueError(f"{path}: service_preserved and no_rebound use yes, no, or blank")
        a = ready[aid]
        hours, kwh, status = 0.0, None, "unconfirmed"
        if r["status"]:
            if not r["observer"] or not r["evidence"]:
                raise ValueError(f"{path}: a reported outcome needs an observer and evidence reference")
            status = r["status"]
        if r["status"] == "completed":
            start, end = _receipt_time(r["started_at"], path + ".started_at"), _receipt_time(r["ended_at"], path + ".ended_at")
            if not (_receipt_time(a["start_at"], path) <= start < end <= _receipt_time(a["end_at"], path)):
                raise ValueError(f"{path}: actual interval must lie within the baseline-reviewed plan window")
            if r["service_preserved"] != "yes" or r["no_rebound"] != "yes":
                status = "needs_review"
            else:
                hours = (end - start).total_seconds() / 3600
                kwh = a["watts"] * hours / 1000 if a["potential_kwh"] is not None else None
        rows.append(dict(r, outcome=status, credited_hours=hours, estimated_kwh=kwh, kind=a["kind"]))
    for aid, a in ready.items():
        if aid not in seen:
            rows.append({"action_id": aid, "outcome": "unconfirmed", "credited_hours": 0,
                         "estimated_kwh": None, "kind": a["kind"]})
    return {"schema": "nocturne-tonight-receipts/1", "plan_sha256": p["plan_sha256"],
            "night_of": p["night_of"], "synthetic": p["synthetic"], "records": rows,
            "completed_count": sum(r["outcome"] == "completed" for r in rows),
            "unconfirmed_count": sum(r["outcome"] == "unconfirmed" for r in rows),
            "review_count": sum(r["outcome"] == "needs_review" for r in rows),
            "estimated_kwh": sum(r["estimated_kwh"] or 0 for r in rows),
            "unquantified_count": sum(r["outcome"] == "completed" and r["kind"] == "switch_off"
                                      and r["estimated_kwh"] is None for r in rows),
            "containment_hours": sum(r["credited_hours"] for r in rows if r["kind"] == "close_blinds"),
            "claim": "Self-reported completion, not independent verification. Energy remains a baseline-dependent estimate. "
                     "Blinds receive no electricity credit. No citywide skyglow or bird-collision benefit is inferred."}


def receipt_template(p):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=RECEIPT_FIELDS)
    writer.writeheader()
    for a in p["actions"]:
        if a["status"] == "owner_ready":
            writer.writerow({"plan_sha256": p["plan_sha256"], "action_id": a["id"]})
    return stream.getvalue()


def read_receipts(text):
    try:
        reader = csv.DictReader(io.StringIO(text), strict=True)
        if reader.fieldnames != RECEIPT_FIELDS:
            raise ValueError("receipts CSV: use the columns in the exported template, in their original order")
        rows = list(reader)
    except csv.Error as e:
        raise ValueError(f"receipts CSV: {e}") from None
    if any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError("receipts CSV: a row has extra or missing columns")
    return rows


def calendar(p):
    """One explicit night, two manual handoff events. Never schedules a device."""
    stamp = p["night_of"].replace("-", "") + "T120000Z"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Nocturne//DC Tonight//EN", "CALSCALE:GREGORIAN"]
    for a in p["actions"]:
        if a["status"] != "owner_ready":
            continue
        for moment, at, instruction in (("start", a["start_at"], KINDS[a["kind"]]),
                                         ("check", a["end_at"], "Check outcome and restore agreed daytime setting")):
            when = _receipt_time(at, "calendar").strftime("%Y%m%dT%H%M%SZ")
            prefix = "[FICTIONAL DEMO] " if p["synthetic"] else ""
            for line in ("BEGIN:VEVENT", f"UID:{p['plan_sha256'][:24]}-{a['id']}-{moment}@nocturne.local",
                         f"DTSTAMP:{stamp}", f"DTSTART:{when}", "DURATION:PT5M",
                         "SUMMARY:" + _ics_text(prefix + instruction + ": " + a["label"]),
                         "LOCATION:" + _ics_text(a["location"]),
                         "DESCRIPTION:" + _ics_text(f"Manual owner task for {a['owner']}. Recheck occupancy and need at the time. "
                                                     f"Preserve: {a['preserve']} Restore: {a['rollback']} "
                                                     "No automatic light control. Record the actual interval in receipts.csv."),
                         "END:VEVENT"):
                lines.extend(_ics_fold(line))
    return "\r\n".join(lines + ["END:VCALENDAR", ""])


def render(p):
    esc = lambda x: html.escape(str(x), quote=True)
    night = {w["action_id"]: w["summary"] for w in p["sky"]["windows"]}
    cards = []
    for a in p["actions"]:
        status = {"owner_ready": "Owner-ready plan", "needs_owner_check": "Owner check needed", "request_only": "Request only"}[a["status"]]
        energy = f"{a['potential_kwh']:.2f} kWh estimated" if a["potential_kwh"] is not None else "Electricity benefit unquantified"
        if a["kind"] == "close_blinds":
            energy = "Containment only; zero electricity credit"
        details = (f"<p>{esc(a['start_at'])} → {esc(a['end_at'])} · {a['hours']:.2f} elapsed hours</p>"
                   f"<p><b>Night:</b> {esc(night.get(a['id'], ''))}</p><p><b>Preserve:</b> {esc(a['preserve'])}</p><p><b>Restore:</b> {esc(a['rollback'])}</p>"
                   f"<p><b>Basis:</b> {esc(a['evidence'])}</p>"
                   f"<p>{esc(energy)}. {esc(a['power_basis'])}</p>" if a["status"] == "owner_ready" else
                   "<ul>" + "".join(f"<li>{esc(r)}</li>" for r in a["reasons"]) + "</ul>")
        request = f"<pre>{esc(a['request_draft'])}</pre>" if a["request_draft"] else ""
        cards.append(f"<article><small>{esc(status)} · {esc(a['id'])}</small><h2>{esc(a['label'])}</h2>"
                     f"<p>{esc(a['location'])} · {esc(a['owner'] or 'Owner not identified')}</p>{details}{request}</article>")
    sources = "".join(f"<li><a href='{esc(s['url'])}'>{esc(s['title'])}</a></li>" for s in SOURCES)
    demo = "<p class='notice'>FICTIONAL EXAMPLE — no real owner, permission or completed work.</p>" if p["synthetic"] else ""
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DC Tonight — {esc(p['title'])}</title><style>
body{{font:16px/1.6 system-ui,sans-serif;max-width:960px;margin:auto;padding:32px;color:#172d32;background:#f4f6f2}}
h1{{font-size:48px;line-height:1.1}}h2{{margin:.3em 0}}small,a{{color:#0b5d63}}article{{padding:22px;margin:18px 0;background:white;border:1px solid #cbd6d4;border-radius:12px}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}.notice{{padding:16px;border-left:4px solid #a96b22;background:#fff2d8}}code{{overflow-wrap:anywhere}}
.sky{{margin:26px 0;padding:22px 24px;background:white;border:1px solid #cbd6d4;border-radius:12px}}.sky-eyebrow{{margin:0 0 12px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#0b5d63}}
.sky-head{{display:flex;gap:14px;align-items:flex-start}}.sky-moon{{width:48px;height:48px;flex:none;margin-top:3px}}.sky-moon circle{{fill:#2b3b40}}.sky-moon path{{fill:#f6efd9}}
.sky-headline{{font:26px/1.2 Georgia,serif;margin:0 0 6px}}.sky-headline em{{display:block;font-size:20px;color:#0b5d63;margin-top:3px}}.sky-line{{margin:0;color:#3d5257}}
.sky-chart{{position:relative;margin:20px 0 4px;padding-bottom:22px;-webkit-print-color-adjust:exact;print-color-adjust:exact}}.sky-grid{{position:absolute;top:0;bottom:22px;width:1px;background:#d5dedd}}
.sky-track{{position:relative;height:10px;margin:5px 0}}.sky-track span{{position:absolute;top:0;height:100%;border-radius:5px;background:#0b5d63}}
.sky-moonup{{height:16px}}.sky-moonup span{{background:#f4e7bd;border:1px solid #c8a54a;color:#5b4610;font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;line-height:14px;padding-left:7px;border-radius:8px;overflow:hidden;white-space:nowrap}}
.sky-strip{{height:20px;border-radius:10px;overflow:hidden}}.sky-strip i{{position:absolute;top:0;height:100%}}.sky-day{{background:#dfe8ec}}.sky-civil{{background:#9db4c4}}.sky-nautical{{background:#5a7a93}}.sky-astronomical{{background:#2c4a63}}.sky-dark{{background:#0f1c27}}
.sky-window p{{position:relative;margin:14px 0 4px;font-size:14px;line-height:1.45}}.sky-window span,.sky-window small{{display:table;background:white;padding-right:6px}}.sky-window small{{font-size:14px;color:#3d5257}}.sky-ticks{{position:absolute;left:0;right:0;bottom:0;height:16px}}.sky-ticks span{{position:absolute;transform:translateX(-50%);font-size:11px;color:#55696d}}.sky-note{{font-size:12px;color:#55696d;margin:12px 0 0}}
@media print{{body{{background:white;padding:0;font-size:11pt}}article,.sky{{break-inside:avoid}}h1{{font-size:30pt}}}}
</style><body><small>NOCTURNE / WASHINGTON, DC / {esc(p['night_of'])}</small><h1>Less spill. Tonight.</h1>
<p>{esc(p['title'])}</p>{demo}<p><b>{p['ready_count']} owner-ready actions · {p['pending_count']} pending checks · {p['request_count']} requests</b></p>
<p>{p['potential_kwh']:.2f} kWh estimated from known circuit power; {p['unquantified_count']} switch actions unquantified.
{p['containment_hours']:.2f} window-group hours of planned containment (not an intensity or area measurement).</p>
<p class="notice">These are manual owner tasks. Recheck occupancy and lighting needs before each action. Keep exits, stairs, crossings, accessibility and required security lighting served. Restore immediately if useful lighting suffers.</p>
{sky_html(p['sky'])}{''.join(cards) or '<p>Add a circuit or a spill observation to make your first action sheet.</p>'}
<h2>Tomorrow: close the loop</h2><p>Fill receipts.csv with the actual start and end times (including UTC offset), observer, and evidence reference. Confirm required service stayed intact and no replacement floodlight or longer operating time cancelled the change. A missed check remains unconfirmed. Retain the original project.json; changing it changes the plan fingerprint.</p>
<p>For streetlights, file the draft yourself through <a href="https://311.dc.gov/">DC 311</a> and retain the request number. DDOT lists 2–5 days for investigations/simple maintenance and up to 12 months for upgrades including lights that are too bright; a request is not a promised same-night repair.</p>
<p>{esc(p['claim'])} Phone photos document a scene; automatic exposure is not calibrated sky photometry.</p>
<p>Migration: {esc(p['migration_note'])}</p><h2>Sources checked {p['sources_checked']}</h2><ul>{sources}</ul>
<p>Plan SHA-256: <code>{p['plan_sha256']}</code></p></body></html>"""


def write_packet(project, directory):
    p = plan(project)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    try:
        for name, content in {
            "project.json": json.dumps(project, indent=2, allow_nan=False) + "\n",
            "plan.json": json.dumps(p, indent=2, allow_nan=False) + "\n",
            "action-sheet.html": render(p), "handoff.ics": calendar(p), "receipts.csv": receipt_template(p),
        }.items():
            (directory / name).write_text(content, encoding="utf-8", newline="")
    except BaseException:
        shutil.rmtree(directory)
        raise
    return p
