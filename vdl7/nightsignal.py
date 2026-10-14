"""The Night Signal: one signed public feed so every light in the city can
keep the curfew, not only the streetlights.

Measured in Tucson, municipal streetlights were about 14 % of the light
behind the city's skyglow (Barentine et al. 2020). The rest is facades,
signs, car parks, sports fields, offices left lit, and in DC monuments and
federal buildings that DDOT does not own. No streetlight controller reaches
them. A shared clock can.

Each evening the CMS publishes, signed with its key:

* tonight's dusk and dawn, astronomical darkness and the Moon;
* the moment each Nocturne phase begins, in UTC (23:00 curfew, 01:00 deep
  night, ...), already resolved through the city's DST rule;
* whether a heavy bird-migration night is forecast (BirdCast or similar);
* for each category of non-street lighting, the recommended share of full
  output in each phase, and how migration nights change it.

Building automation, sign controllers and smart-home hubs poll the JSON and
apply `decide()`; a facilities manager with none of that subscribes to the
same nights as a calendar (`to_ics`). Where the District adopts curfew hours
in law, the feed becomes the compliance clock; until then it is the easiest
way for a willing owner to do the right thing. The same migration input
signs EventKind.MIGRATION events for the streetlights themselves
(`migration_events`).
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from .clock import NIGHT_ELEVATION_DEG, local_to_utc, next_crossing, night_bounds, solar_elevation_exact
from .events import EventKind
from .observe import moon
from .security import SignedMessage, Verifier
from .sites import DEFAULT_SITE, Site

UTC = timezone.utc
SCHEMA = 1
PHASE_CLOCK = [("step", 22, 0), ("curfew", 23, 0), ("deep", 1, 1), ("dawn", 5, 1)]   # (phase, hour, day offset)


@dataclass(frozen=True)
class Category:
    title: str
    levels: Dict[str, float]                 # phase -> maximum share of full output
    migration: Dict[str, float] = field(default_factory=dict)   # phase -> override on migration nights
    open_level: Optional[float] = None       # after curfew while the premises are open or in use
    motion: bool = False                     # full output on motion, at any hour
    note: str = ""


CATEGORIES: Dict[str, Category] = {
    "facade": Category("Architectural, facade and monument floodlighting",
                       {"evening": 1.0, "step": 1.0, "curfew": 0.0, "deep": 0.0, "dawn": 0.0},
                       {"evening": 0.0, "step": 0.0},
                       note="Light the building for the people who are there to see it, then go dark."),
    "signage": Category("Commercial signs and digital billboards",
                        {"evening": 1.0, "step": 1.0, "curfew": 0.0, "deep": 0.0, "dawn": 0.0},
                        {"evening": 0.5, "step": 0.5}, open_level=0.3,
                        note="Signs of businesses still open may stay at 30 % until they close."),
    "office_interior": Category("Interior lights visible from outside above the fourth floor",
                                {"evening": 1.0, "step": 1.0, "curfew": 0.0, "deep": 0.0, "dawn": 0.0},
                                {"evening": 0.0, "step": 0.0}, open_level=1.0,
                                note="Lights out or blinds down when the floor is empty; on migration "
                                     "nights from dusk (the Lights Out programmes' ask)."),
    "parking": Category("Surface car parks and garage roofs",
                        {"evening": 1.0, "step": 1.0, "curfew": 0.5, "deep": 0.5, "dawn": 0.5},
                        motion=True, note="Half output after curfew, full on motion."),
    "sports": Category("Sports fields and courts",
                       {"evening": 1.0, "step": 1.0, "curfew": 0.0, "deep": 0.0, "dawn": 0.0},
                       open_level=1.0, note="While in use only; off within 15 minutes of play ending."),
    "landscape": Category("Landscape, decorative and residential accent lighting",
                          {"evening": 1.0, "step": 1.0, "curfew": 0.0, "deep": 0.0, "dawn": 0.0},
                          {"evening": 0.0, "step": 0.0}),
    "security": Category("Security lighting",
                         {"evening": 0.0, "step": 0.0, "curfew": 0.0, "deep": 0.0, "dawn": 0.0},
                         motion=True, note="Motion-activated at every hour: light when someone is there."),
}


def migration_season(day: date) -> bool:
    """Peak migration windows used by Lights Out programmes in the eastern
    US: 15 March - 31 May and 15 August - 15 November."""
    md = (day.month, day.day)
    return (3, 15) <= md <= (5, 31) or (8, 15) <= md <= (11, 15)


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def _local_noon(site: Site, day: date) -> datetime:
    return local_to_utc(datetime(day.year, day.month, day.day, 12), site.tz)


def dark_window(site: Site, night_of: date) -> Tuple[Optional[datetime], Optional[datetime], bool]:
    """(from, to, polar_night): when the signal applies. Dusk to dawn with
    the sun 3 deg down, as the streetlights switch. In polar night, when the
    sun stays below that all day, from local noon until it returns or the
    next noon; the night polar night begins ends at the next noon. None
    under the midnight sun."""
    dusk, dawn = night_bounds(site.lat, site.lon, night_of, tz=site.tz)
    next_noon = _local_noon(site, night_of + timedelta(days=1))
    polar = False
    if dusk is None:
        noon = _local_noon(site, night_of)
        if solar_elevation_exact(site.lat, site.lon, noon) >= NIGHT_ELEVATION_DEG:
            return None, None, False                                   # midnight sun: no night
        polar = True
        dusk = noon
        dawn = next_crossing(site.lat, site.lon, noon, NIGHT_ELEVATION_DEG, descending=False, max_hours=24.0)
    end = min(dawn, next_noon) if dawn else next_noon
    return (dusk, end, polar) if end > dusk else (None, None, False)


def signal(night_of: date, site: Site = DEFAULT_SITE, migration: Optional[Dict[str, str]] = None,
           issuer: str = "Nocturne CMS", issued: Optional[datetime] = None) -> dict:
    """The Night Signal document for the night that begins on `night_of`."""
    dusk, dawn = night_bounds(site.lat, site.lon, night_of, tz=site.tz)
    adusk, adawn = night_bounds(site.lat, site.lon, night_of, threshold=-18.0, tz=site.tz)
    start, end, polar = dark_window(site, night_of)
    phases = [{"phase": "evening", "start": _iso(start)}]
    for name, hour, offset in PHASE_CLOCK:
        d = night_of + timedelta(days=offset)
        phases.append({"phase": name, "start": _iso(local_to_utc(datetime(d.year, d.month, d.day, hour), site.tz))})
    curfew = next(p["start"] for p in phases if p["phase"] == "curfew")
    mid = (start + (end - start) / 2) if (start and end) else local_to_utc(
        datetime(night_of.year, night_of.month, night_of.day, 23, 59), site.tz)
    mo = moon(mid, site.lat, site.lon)
    curfew_t = datetime.fromisoformat(curfew.replace("Z", "+00:00"))
    return {
        "kind": "night_signal", "schema": SCHEMA, "issuer": issuer,
        "issued": _iso(issued or datetime.now(UTC)),
        "site": {"key": site.key, "name": site.name, "lat": site.lat, "lon": site.lon, "tz": site.tz},
        "night_of": night_of.isoformat(),
        "sun": {"dusk": _iso(dusk), "dawn": _iso(dawn), "astronomical_dusk": _iso(adusk),
                "astronomical_dawn": _iso(adawn)},
        "dark": {"from": _iso(start), "to": _iso(end), "polar_night": polar},
        "moon": {"illuminated": round(mo.illuminated, 2),
                 "up_at_curfew": moon(curfew_t, site.lat, site.lon).alt_deg > 0},
        "phases": phases, "curfew": curfew,
        "migration": {"active": bool(migration), "season": migration_season(night_of),
                      **({k: str(v) for k, v in (migration or {}).items()})},
        "categories": {k: {"title": c.title, "levels": c.levels, "migration": c.migration,
                           "open_level": c.open_level, "motion": c.motion, "note": c.note}
                       for k, c in CATEGORIES.items()},
    }


# ----------------------------------------------------------- publication
def sign(doc: dict, signer) -> dict:
    """{'payload': canonical JSON, 'signature_b64': Ed25519 over it}."""
    msg = signer.sign_obj(doc)
    return {"payload": msg.payload.decode("utf-8"), "signature_b64": base64.b64encode(msg.signature).decode("ascii")}


def verify(published: dict, verifier: Verifier) -> Optional[dict]:
    """The document if the signature checks, else None."""
    try:
        payload = published["payload"].encode("utf-8")
        sig = base64.b64decode(published["signature_b64"])
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    if not verifier.verify(payload, sig):
        return None
    doc = json.loads(payload)
    return doc if isinstance(doc, dict) and doc.get("kind") == "night_signal" else None


# ------------------------------------------------------------ subscribers
def phase_at(doc: dict, utc: datetime) -> Optional[str]:
    """The phase in force at `utc`, or None in daylight."""
    dark = doc["dark"]
    if not (dark["from"] and dark["to"]):
        return None
    t = utc.astimezone(UTC)
    if not (_t(dark["from"]) <= t < _t(dark["to"])):
        return None
    current = "evening"
    for p in doc["phases"]:
        if _t(p["start"]) <= t:
            current = p["phase"]
    return current


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def decide(doc: dict, category: str, utc: datetime, open_now: bool = False,
           motion: bool = False) -> Tuple[Optional[float], str]:
    """What a light of `category` should do at `utc`: (share of full output,
    reason). None means daylight: the signal has no instruction."""
    phase = phase_at(doc, utc)
    if phase is None:
        return None, "daylight"
    c = doc["categories"][category]
    if c["motion"] and motion:
        return 1.0, "motion"
    level = c["levels"][phase]
    why = f"{phase} phase"
    if doc["migration"]["active"] and phase in c["migration"]:
        level, why = min(level, c["migration"][phase]), f"{phase} phase, migration night"
    if open_now and c["open_level"] is not None and phase in ("curfew", "deep", "dawn"):
        level, why = max(level, c["open_level"]), f"{phase} phase, open"
    return level, why


# ------------------------------------------------------------- calendar
def _ics_text(s: str) -> str:
    """RFC 5545 3.3.11 TEXT escaping."""
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_fold(line: str) -> List[str]:
    """RFC 5545 3.1: lines of at most 75 octets, continued with a space."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 75:
            out.append(cur)
            cur = " "
        cur += ch
    return out + [cur]


def _ics_time(iso: str) -> str:
    return iso.replace("-", "").replace(":", "")


def _site_tag(doc: dict) -> str:
    """The site in an event's UID, so two cities' feeds never share one
    (RFC 5545 3.8.4.7: a UID is globally unique): the preset key, or the
    coordinates for a document without one."""
    s = doc.get("site") or {}
    tag = s.get("key") or (f"{s['lat']:.4f}_{s['lon']:.4f}" if "lat" in s and "lon" in s else "site")
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in str(tag))


def to_ics(docs: Iterable[dict], name: str = "Night Signal") -> str:
    """An iCalendar feed: one event per night from curfew until the dark
    ends, and a whole-night 'Lights Out' event on migration nights. Under
    the midnight sun the curfew runs to the 05:00 dawn phase, so every
    night has its event."""
    docs = list(docs)
    if not docs:
        raise ValueError("an iCalendar feed needs at least one night")
    now = _ics_time(_iso(datetime.now(UTC)) or "")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Nocturne//Night Signal//EN", f"X-WR-CALNAME:{_ics_text(name)}"]
    for d in docs:
        stamp = _ics_time(d.get("issued") or "") or now
        dark = d["dark"]
        dawn_phase = next(p["start"] for p in d["phases"] if p["phase"] == "dawn")
        events = [("curfew", d["curfew"], dark["to"] or dawn_phase, "Lighting curfew: facades, signs and empty floors off")]
        if d["migration"]["active"]:
            events.append(("migration", dark["from"], dark["to"], "Lights Out: heavy bird migration forecast tonight"))
        for kind, start, end, summary in events:
            if not (start and end) or _t(end) <= _t(start):
                continue
            for line in ("BEGIN:VEVENT", f"UID:{d['night_of']}-{kind}@nocturne-{_site_tag(d)}", f"DTSTAMP:{stamp}",
                         f"DTSTART:{_ics_time(start)}", f"DTEND:{_ics_time(end)}", f"SUMMARY:{_ics_text(summary)}",
                         "END:VEVENT"):
                lines += _ics_fold(line)
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ------------------------------------------------- the streetlights' half
def migration_events(cms, segments: Iterable[str], doc: dict, now: datetime) -> List[SignedMessage]:
    """Signed EventKind.MIGRATION events for the streetlights, one per
    segment, live from now until the night's dawn. Nothing is sent once
    the night is over, or while its dawn is more than the firmware's 24 h
    event lifetime away: an event sent that early would expire before the
    night it is for, so the CMS sends it on a later run."""
    end = doc["dark"]["to"]
    if not doc["migration"]["active"] or not end:
        return []
    ttl = (_t(end) - now.astimezone(UTC)).total_seconds()
    if not (0.0 < ttl <= 86400.0):
        return []
    payload = {k: v for k, v in doc["migration"].items() if k not in ("active", "season")}
    return [cms.event(EventKind.MIGRATION, ttl, seg, payload, event_id=f"mig-{doc['night_of']}", issued=now)
            for seg in segments]
