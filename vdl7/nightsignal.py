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

from .clock import local_to_utc, night_bounds, to_local
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


def signal(night_of: date, site: Site = DEFAULT_SITE, migration: Optional[Dict[str, str]] = None,
           issuer: str = "Nocturne CMS", issued: Optional[datetime] = None) -> dict:
    """The Night Signal document for the night that begins on `night_of`."""
    dusk, dawn = night_bounds(site.lat, site.lon, night_of, tz=site.tz)
    adusk, adawn = night_bounds(site.lat, site.lon, night_of, threshold=-18.0, tz=site.tz)
    phases = [{"phase": "evening", "start": _iso(dusk)}]
    for name, hour, offset in PHASE_CLOCK:
        d = night_of + timedelta(days=offset)
        phases.append({"phase": name, "start": _iso(local_to_utc(datetime(d.year, d.month, d.day, hour), site.tz))})
    curfew = next(p["start"] for p in phases if p["phase"] == "curfew")
    mid = (dusk + (dawn - dusk) / 2) if (dusk and dawn) else local_to_utc(
        datetime(night_of.year, night_of.month, night_of.day, 23, 59), site.tz)
    mo = moon(mid, site.lat, site.lon)
    curfew_t = datetime.fromisoformat(curfew.replace("Z", "+00:00"))
    return {
        "kind": "night_signal", "schema": SCHEMA, "issuer": issuer,
        "issued": _iso(issued or datetime.now(UTC)),
        "site": {"name": site.name, "lat": site.lat, "lon": site.lon, "tz": site.tz},
        "night_of": night_of.isoformat(),
        "sun": {"dusk": _iso(dusk), "dawn": _iso(dawn), "astronomical_dusk": _iso(adusk),
                "astronomical_dawn": _iso(adawn)},
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
    sun = doc["sun"]
    if not (sun["dusk"] and sun["dawn"]):
        return None
    t = utc.astimezone(UTC)
    if not (_t(sun["dusk"]) <= t < _t(sun["dawn"])):
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
def to_ics(docs: Iterable[dict], name: str = "Night Signal") -> str:
    """An iCalendar feed: one event per night from curfew to dawn, and a
    dusk-to-dawn 'Lights Out' event on migration nights."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Nocturne//Night Signal//EN", f"X-WR-CALNAME:{name}"]
    stamp = None
    for d in docs:
        stamp = (d["issued"] or "").replace("-", "").replace(":", "")
        sun = d["sun"]
        events = [("curfew", d["curfew"], sun["dawn"], "Lighting curfew: facades, signs and empty floors off")]
        if d["migration"]["active"]:
            events.append(("migration", sun["dusk"], sun["dawn"], "Lights Out: heavy bird migration forecast tonight"))
        for kind, start, end, summary in events:
            if not (start and end):
                continue
            lines += ["BEGIN:VEVENT", f"UID:{d['night_of']}-{kind}@nocturne", f"DTSTAMP:{stamp}",
                      f"DTSTART:{start.replace('-', '').replace(':', '')}",
                      f"DTEND:{end.replace('-', '').replace(':', '')}", f"SUMMARY:{summary}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ------------------------------------------------- the streetlights' half
def migration_events(cms, segments: Iterable[str], doc: dict, now: datetime) -> List[SignedMessage]:
    """Signed EventKind.MIGRATION events for the streetlights, one per
    segment, valid until tonight's dawn (at most 24 h)."""
    if not doc["migration"]["active"] or not doc["sun"]["dawn"]:
        return []
    ttl = max(60.0, min(86400.0, (_t(doc["sun"]["dawn"]) - now.astimezone(UTC)).total_seconds()))
    payload = {k: v for k, v in doc["migration"].items() if k not in ("active", "season")}
    return [cms.event(EventKind.MIGRATION, ttl, seg, payload, event_id=f"mig-{doc['night_of']}", issued=now)
            for seg in segments]
