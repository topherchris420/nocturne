"""`nocturne` command line.

The node
    nocturne trace --road local [--site sydney]
    nocturne trace --road arterial --offline-at 22:00 --event emergency@00:40:60
    nocturne keygen --out cms_key.pem                      # CMS signing key, prints the node public key
    nocturne bundle --key cms_key.pem --version 2 [--zones zones.json] --out bundle.json

The city
    nocturne business-case [--site dc] [--price 0.13] [--co2 0.30]     # a year, DC's real fleet
    nocturne schedule --plan plan.csv --wave 1 --out phase0/           # Phase 0 programmes for the CMS
    nocturne sky [--share 0.15] [--measured rock-creek=18.4] [--retrofits 10]
    nocturne bug fixture.ies                               # TM-15 BUG rating and uplight
    nocturne trespass fixture.ies --height 9 --setback 10 --window 5 --road local
    nocturne signal --date 2026-10-14 [--migration] [--key cms_key.pem] [--ics curfew.ics --days 30]
    nocturne verify station.dat --go-live 2026-11-01       # did the sky get darker?
    nocturne pilot --seed "text published before the draw" [--out plan.csv]
    nocturne pilot --power 0.0014 1.2                      # segment-nights to detect a 20 % change
    nocturne brake --plan plan.csv --crashes night_crashes.csv --through 2027-02-28   # before each wave

Models
    nocturne restore examples/restoration/district.json --report restoration.html
    nocturne experiment --source facades --start 2027-01-04 --seed public-seed --out trial
    nocturne attribute trial/trial.json trial/readings.csv
    nocturne spectral [--spd my_engine=lm79.csv]
    nocturne simulate --out out
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import os
import re
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Tuple

from . import spectral
from .bench import Bench
from .clock import local_to_utc, parse_local
from .events import EventKind, Priority
from .profiles import PHASE_ORDER, RoadClass, default_bundle, validate_bundle
from .security import Ed25519Signer
from .sites import SITES, site


def _first_at(start_local: datetime, hm: Tuple[int, int], tz: str) -> datetime:
    """The first moment, at or after the trace starts, that the local clock
    reads `hm`: 00:40 in a trace from 18:00 is after midnight, 19:00 is the
    same evening."""
    at = start_local.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    if at < start_local:
        at += timedelta(days=1)
    return local_to_utc(at, tz)


def cmd_trace(a) -> int:
    b = Bench(RoadClass(a.road), start=a.start, hin=a.hin, tunable=a.tunable, online=not a.offline,
              site=site(a.site))
    tz = b.site.tz
    start_local, start_utc, end_utc = datetime.fromisoformat(a.start), b.utc, parse_local(a.end, tz)
    if end_utc <= start_utc:
        raise ValueError(f"--end {a.end} is not after --start {a.start}")
    off_utc = _first_at(start_local, a.offline_at, tz) if a.offline_at else None
    events = [(kind, _first_at(start_local, hm, tz), ttl_min, level) for kind, hm, ttl_min, level in a.event or []]
    for what, when in ([("--offline-at", off_utc)] if off_utc else []) + [(f"--event {e[0]}", e[1]) for e in events]:
        if when >= end_utc:
            print(f"nocturne: warning: {what} falls after --end {a.end}; it will not happen in this trace",
                  file=sys.stderr)
    print(f"{'local':6s} {'mode':10s} {'phase':8s} {'lit':3s} {'base':>4s} {'act':>4s} {'target':>6s} "
          f"{'level':>5s} {'white':>5s} {'amber':>5s}  reasons")
    last_key, fired = None, set()
    while b.utc < end_utc:
        loc = b.local
        hhmm = loc.strftime("%H:%M")
        if off_utc is not None and b.utc >= off_utc and "off" not in fired:
            b.go_offline()
            fired.add("off")
            print(f"--- backhaul lost at {hhmm}")
        for i, (kind, when, ttl_min, level) in enumerate(events):
            if b.utc >= when and i not in fired:
                k = EventKind(kind)
                payload = {"level": level} if level is not None else {}
                prio = Priority.OPERATOR if k == EventKind.OVERRIDE else Priority.NONE
                via = "backhaul" if b.online else "mesh"
                b.send(k, ttl_min * 60, payload, prio, via=via)
                fired.add(i)
                print(f"--- event {kind} at {hhmm} via {via}, ttl {ttl_min} min")
        elapsed_min = int((b.utc - start_utc).total_seconds() // 60)
        out = b.step(a.dt)
        key = elapsed_min // a.every                     # a row every `every` minutes from the start
        if key != last_key:
            last_key = key
            print(f"{hhmm:6s} {out.mode.value:10s} {out.phase.value:8s} {'y' if out.lit else '-':3s} {out.base:4d} "
                  f"{out.activity:4.2f} {out.target:6.1f} {out.level:5.1f} {out.white:5.1f} {out.amber:5.1f}  "
                  f"{' '.join(out.reasons[2:] + list(out.alarms))}")
    return 0


def cmd_spectral(a) -> int:
    for item in a.spd or []:
        name, sep, path = item.partition("=")
        if not (sep and name and path):
            raise ValueError(f"--spd {item!r}: use name=path.csv, e.g. my_engine=lm79.csv")
        m = spectral.metrics(name, spectral.load_spd_csv(path))
        spectral.table()[name] = m                      # report it alongside the models
    rows = spectral.relative_table()
    if a.json:
        print(json.dumps(rows, indent=2))
        return 0
    print(f"{'spectrum':18s} {'CCT':>5s} {'Duv':>8s} {'Rayl':>5s} {'Sky':>5s} {'Mie':>5s} {'mDER':>5s} {'<500':>6s} {'LER':>6s}")
    for r in rows:
        print(f"{r['spectrum']:18s} {r['cct_K']:5d} {r['duv']:+8.4f} {r['rayleigh_rel']:5.2f} {r['skyglow_scotopic_rel']:5.2f} "
              f"{r['mie_rel']:5.2f} {r['mel_der']:5.2f} {r['blue_fraction']:6.1%} {r['ler_lm_per_W']:6.1f}")
    print("per photopic lumen, 4000K = 1.00; Sky = Rayleigh x scotopic (what the dark-adapted eye sees)")
    return 0


def cmd_simulate(a) -> int:
    from sim.run_night import SCENARIOS, main as sim_main
    unknown = [s for s in a.scenario or [] if s not in SCENARIOS]
    if unknown:
        raise ValueError(f"unknown scenario {', '.join(map(repr, unknown))}; known: {', '.join(SCENARIOS)}")
    argv = ["--out", a.out, "--dt", str(a.dt)]
    for s in a.scenario or []:
        argv += ["--scenario", s]
    return sim_main(argv)


def cmd_keygen(a) -> int:
    if os.path.exists(a.out) and not a.force:
        print(f"{a.out} exists; pass --force to overwrite", file=sys.stderr)
        return 1
    signer = Ed25519Signer()
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(signer.private_pem())
    print(f"wrote private key {a.out} (mode 600): keep it on the CMS signing host only", file=sys.stderr)
    print("node public key (provision into each VDL-7 secure element):")
    print(base64.b64encode(signer.public().raw()).decode())
    return 0


def cmd_bundle(a) -> int:
    with open(a.key, "rb") as f:
        signer = Ed25519Signer.from_pem(f.read())
    bundle = default_bundle(version=a.version, issued=a.issued)
    if a.zones:
        bundle.zones = _zones_from(a.zones)
    errs = validate_bundle(bundle)
    if errs:
        print("refusing to sign an invalid bundle:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 1
    msg = signer.sign_obj(bundle.to_dict())
    doc = {"payload": msg.payload.decode(), "signature_b64": base64.b64encode(msg.signature).decode(),
           "public_key_b64": base64.b64encode(signer.public().raw()).decode(),
           "alg": "Ed25519 over the canonical payload bytes"}
    text = json.dumps(doc, indent=2)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text)
        print("wrote", a.out, file=sys.stderr)
    else:
        print(text)
    return 0


def cmd_business_case(a) -> int:
    from .annual import Economics, dc_fleet, format_report, run_year, spec_fleet
    fleet = dc_fleet() if a.fleet == "dc" else spec_fleet(a.lights)
    r = run_year(fleet, site=site(a.site), year=a.year, unsensed_floor=a.floor,
                 econ=Economics(usd_per_kwh=a.price, tco2_per_mwh=a.co2))
    print(json.dumps(r, indent=2) if a.json else format_report(r))
    return 0


def cmd_sky(a) -> int:
    from .annual import dc_fleet
    from .skyglow import CLASSES, PLACES_DC, format_sky, lighting_for, load_grid, plan_retrofits, sky_scenarios
    known = [p.key for p in PLACES_DC]

    def check(key: str, option: str) -> str:
        if key not in known:
            raise ValueError(f"{option}: unknown place {key!r}; known: {', '.join(known)}")
        return key

    measured = {}
    for item in a.measured or []:
        k, sep, v = item.partition("=")
        try:
            msas = float(v)
        except ValueError:
            msas = math.nan
        if not sep or not math.isfinite(msas):
            raise ValueError(f"--measured {item!r}: use place=msas, e.g. rock-creek=18.4")
        measured[check(k.strip(), "--measured")] = msas
    wanted = {check(k, "--place") for k in a.place or []}
    places = [p for p in PLACES_DC if not wanted or p.key in wanted]
    fleet = dc_fleet()
    cct = {c: fleet.classes[c].mix() for c in CLASSES}
    cells = load_grid()
    rows = sky_scenarios(cells, places, cct, share=a.share, other_curfew_cut=a.cut, measured=measured or None)
    steps = plan_retrofits(cells, places, lighting_for("phase1", 1.5, cct), top=a.retrofits) if a.retrofits else []
    if a.json:                                     # one JSON document: the rows, or rows and retrofits
        print(json.dumps({"places": rows, "retrofits": [asdict(s) for s in steps]} if a.retrofits else rows,
                         indent=2))
        return 0
    print(format_sky(rows))
    if a.retrofits:
        print("\nPost-top globes to fix first (top reflectors), ranked by sky regained at these places per kW:")
        for s in steps:
            best = max(s.gain, key=s.gain.get)
            print(f"  {s.lat:.4f},{s.lon:.4f}  {s.globes_kw:5.1f} kW of globes  "
                  f"-{s.gain[best]:.1%} of the streetlight sky at {best}")
    return 0


def cmd_bug(a) -> int:
    from .photometry import load_ies
    phot = load_ies(a.ies)
    bug = phot.bug()
    z = bug.zones
    if a.json:
        print(json.dumps({"bug": str(bug), "B": bug.B, "U": bug.U, "G": bug.G, "limiting": bug.limiting,
                          "ulr": phot.ulr, "zonal_lumens": {k: round(v, 1) for k, v in z.items()},
                          "symmetry": phot.symmetry}, indent=2))
        return 0
    print(f"{a.ies}: {bug}   (limited by {bug.limiting['B']}, {bug.limiting['U']}, {bug.limiting['G']}; "
          f"{phot.symmetry} photometry{', Type V glare table' if bug.symmetric_table else ''})")
    print(f"total {z['total']:,.0f} lm, upward {z['up']:,.1f} lm (ULR {phot.ulr:.2%})"
          + (f", {z['total'] / phot.input_watts:.0f} lm/W" if phot.input_watts else ""))
    print("  ".join(f"{k} {z[k]:,.0f}" for k in ("BL", "BM", "BH", "BVH", "FL", "FM", "FH", "FVH", "UL", "UH")))
    if bug.U > 0:
        print("not U0: fails the Section 3 uplight requirement")
    return 0


def cmd_trespass(a) -> int:
    from .photometry import load_ies, trespass_report
    from .profiles import DEFAULT_MIX, DEFAULT_PROFILES
    phot = load_ies(a.ies)
    prof = DEFAULT_PROFILES[RoadClass(a.road)]
    levels = {ph.value: float(lv) for ph, lv in zip(PHASE_ORDER, prof.levels)}
    spectra = {ph.value: ("PC-Amber" if (a.tunable and DEFAULT_MIX[ph][1] == 100) else a.spectrum) for ph in PHASE_ORDER}
    rows = trespass_report(phot, a.height, a.setback, a.window, levels, spectra, env_zone=a.zone)
    print(f"window {a.setback:g} m behind a {a.height:g} m pole, {a.window:g} m up; CIE 150 zone {a.zone}")
    print(f"{'phase':8s} {'level':>5s} {'spectrum':>9s} {'Ev lx':>7s} {'limit':>6s} {'mel-EDI lx':>10s}  verdict")
    for r in rows:
        verdict = []
        verdict.append("ok" if r["within_cie150"] else "over CIE 150")
        verdict.append("below 1 lx sleep guide" if r["below_sleep_guide"] else "above 1 lx sleep guide")
        print(f"{r['phase']:8s} {r['level_pct']:5.0f} {r['spectrum']:>9s} {r['ev_lux']:7.2f} {r['cie150_limit_lux']:6.1f} "
              f"{r['mel_edi_lux']:10.2f}  {', '.join(verdict)}")
    return 0


def cmd_signal(a) -> int:
    from .nightsignal import sign, signal, to_ics
    s = site(a.site)
    first = a.date or date.today()
    mig = {"source": a.migration_source} if a.migration else None
    signer = None
    if a.key:                                      # read the key first: a bad one must not leave a feed behind
        with open(a.key, "rb") as f:
            signer = Ed25519Signer.from_pem(f.read())
    docs = [signal(first + timedelta(days=i), site=s, migration=mig if i == 0 else None)
            for i in range(a.days)]
    if a.ics:
        with open(a.ics, "w", newline="") as f:
            f.write(to_ics(docs))
        print(f"wrote {a.ics}: {len(docs)} nights", file=sys.stderr)     # stdout is the JSON alone
    out = sign(docs[0], signer) if signer else docs[0]
    print(json.dumps(out, indent=2))
    return 0


def cmd_verify(a) -> int:
    from .observe import read_sqm, verify
    s = site(a.site)
    r = verify(read_sqm(a.log), a.go_live, s.lat, s.lon, s.tz)
    print(f"{a.log}: {r['readings']:,} readings, {r['dark']:,} in astronomical darkness with the Moon down, "
          f"{r['nights_with_step']} clear nights around the curfew")
    print(f"change in the 23:00 curfew step after go-live: {r['curfew_step_change'] or 'not enough nights'}")
    print(f"change in the post-curfew sky (23:15-02:00):  {r['post_curfew_change'] or 'not enough nights'}")
    for note in r["notes"]:
        print("note:", note)
    print("positive = darker; the curfew-step change is the one weather and season cannot fake")
    return 0 if r["curfew_step_change"] or r["post_curfew_change"] else 1


def cmd_pilot(a) -> int:
    from .pilot import exposure_needed, load_segments, stepped_wedge
    if a.power:
        rate, rr = a.power
        n = exposure_needed(rate, rr)
        print(f"{n:,.0f} segment-nights per arm to detect a rate ratio of {rr:g} on a baseline of {rate:g} "
              f"events per segment-night (two-sided 5 %, 80 % power)")
        return 0
    if not a.seed:
        print("--seed is required: a string published before the draw", file=sys.stderr)
        return 1
    segs = load_segments(a.segments) if a.segments else load_segments()
    plan = stepped_wedge(segs, a.seed, waves=a.waves, start=a.start, wave_days=a.wave_days)
    for w in range(1, plan.waves + 1):
        n = sum(1 for v in plan.assignment.values() if v == w)
        lights = sum(sg.lights for sg in segs if plan.assignment[sg.id] == w)
        print(f"wave {w}: {n:,} segments, {lights:,} lights, switch on {plan.wave_start(w).isoformat()}")
    if a.out:
        plan.to_csv(a.out, segs)
        print("wrote", a.out, file=sys.stderr)
    return 0


def _zones_from(path):
    """Zone overlays from JSON, read by the bundle's own strict parser: a
    level of 80.9 or 100.9 is refused, never rounded into a valid one."""
    from .profiles import ProfileBundle
    with open(path) as f:
        try:
            raw = json.load(f)
        except ValueError as e:
            raise ValueError(f"--zones {path}: not JSON ({e})") from None
    try:
        return ProfileBundle.from_dict(dict(default_bundle().to_dict(), zones=raw)).zones
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        raise SystemExit(f"--zones {path}: {e}") from None


def _pct(text: str) -> float:
    from .schedule import check_floor
    try:
        return check_floor(float(text))
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def _iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date: use YYYY-MM-DD") from None


def _iso_date_text(text: str) -> str:
    return _iso_date(text).isoformat()


def _local_time_text(text: str) -> str:
    try:
        t = datetime.fromisoformat(text.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a local date and time: use 'YYYY-MM-DD HH:MM'") from None
    if t.tzinfo is not None:
        raise argparse.ArgumentTypeError(f"{text!r}: give the site's local time, without a UTC offset")
    return text.strip()


def _clock(text: str) -> Tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", text)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise argparse.ArgumentTypeError(f"{text!r} is not a local clock time: use H:MM or HH:MM, 24-hour")
    return int(m.group(1)), int(m.group(2))


def _event(text: str) -> Tuple[str, Tuple[int, int], int, object]:
    """kind@HH:MM[:ttl_min[:level]] -> (kind, (h, m), ttl_min, level or None)."""
    kinds = [k.value for k in EventKind]
    kind, sep, rest = text.partition("@")
    parts = rest.split(":")
    usage = f"{text!r}: use kind@HH:MM[:ttl_min[:level]], e.g. emergency@00:40:60 or override@23:00:120:50"
    if not sep or len(parts) < 2 or len(parts) > 4:
        raise argparse.ArgumentTypeError(usage)
    if kind not in kinds:
        raise argparse.ArgumentTypeError(f"{text!r}: unknown event kind {kind!r}; known: {', '.join(kinds)}")
    hm = _clock(f"{parts[0]}:{parts[1]}")
    try:
        ttl = int(parts[2]) if len(parts) > 2 else 60
        level = int(parts[3]) if len(parts) > 3 else None
    except ValueError:
        raise argparse.ArgumentTypeError(usage) from None
    if ttl < 1:
        raise argparse.ArgumentTypeError(f"{text!r}: ttl must be at least 1 minute")
    if level is not None and not 0 <= level <= 100:
        raise argparse.ArgumentTypeError(f"{text!r}: level must be 0-100 %")
    if kind == EventKind.OVERRIDE.value and level is None:
        raise argparse.ArgumentTypeError(f"{text!r}: an override needs a level, e.g. override@23:00:120:50")
    return kind, hm, ttl, level


def _number(text: str, integer: bool) -> float:
    try:
        v = int(text) if integer else float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a {'whole ' if integer else ''}number") from None
    if not math.isfinite(v):
        raise argparse.ArgumentTypeError(f"{text!r} is not a finite number")
    return v


def _positive_int(text: str) -> int:
    v = _number(text, True)
    if v < 1:
        raise argparse.ArgumentTypeError(f"{text} must be at least 1")
    return v


def _nonneg_int(text: str) -> int:
    v = _number(text, True)
    if v < 0:
        raise argparse.ArgumentTypeError(f"{text} cannot be negative")
    return v


def _positive_float(text: str) -> float:
    v = _number(text, False)
    if v <= 0:
        raise argparse.ArgumentTypeError(f"{text} must be greater than 0")
    return v


def _nonneg_float(text: str) -> float:
    v = _number(text, False)
    if v < 0:
        raise argparse.ArgumentTypeError(f"{text} cannot be negative")
    return v


def cmd_brake(a) -> int:
    from .pilot import brake, load_plan, tally
    rows = load_plan(a.plan)
    switch_on = {r["segment"]: date.fromisoformat(r["switch_on"]) for r in rows}
    waves = len({r["wave"] for r in rows})
    with open(a.crashes, newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in ("segment", "night") if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{a.crashes}: needs the columns segment,night (missing {', '.join(missing)})")
        events = []
        for n, r in enumerate(reader, start=2):
            try:
                events.append((r["segment"], date.fromisoformat((r["night"] or "").strip())))
            except ValueError:
                raise ValueError(f"{a.crashes}, row {n}: night {r['night']!r} is not a YYYY-MM-DD date") from None
    periods, skipped = tally(switch_on, events, a.through)
    looks = a.looks or max(1, waves - 1)
    decision, t = brake([p.stratum for p in periods], looks=looks)
    print(f"{'period from':12s} {'nights':>6s} {'on: events':>11s} {'seg-nights':>11s} {'off: events':>12s} {'seg-nights':>11s}")
    for p in periods:
        print(f"{p.start.isoformat():12s} {p.nights:6d} {p.events_on:11d} {p.exposure_on:11,.0f} "
              f"{p.events_off:12d} {p.exposure_off:11,.0f}")
    if skipped:
        print(f"{skipped} events outside the plan or the dates were not counted")
    print(f"switched vs not yet switched, within periods: {t}")
    print(f"look threshold: one-sided p < {0.05 / looks:.4f} (5 % split over {looks} looks)")
    print("PAUSE the next wave and revert the affected class" if decision == "pause" else "continue")
    return 2 if decision == "pause" else 0


def cmd_schedule(a) -> int:
    from .pilot import load_plan
    from .schedule import export, programs
    if a.wave is not None and not a.plan:
        raise ValueError("--wave picks segments from a plan: give the plan with --plan plan.csv")
    plan_rows = load_plan(a.plan) if a.plan else None          # check the plan before writing anything
    bundle = default_bundle(version=a.version)
    if a.zones:
        bundle.zones = _zones_from(a.zones)
    errs = validate_bundle(bundle)
    if errs:
        print("refusing to export an invalid bundle:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 1
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "programs.json"), "w") as f:
        f.write(export(bundle, tz=site(a.site).tz, unsensed_floor=a.floor))
    for name, prog in programs(bundle, a.floor).items():
        print(f"{name:28s} " + "  ".join(f"{st['at']} {st['level']}%" for st in prog["steps"]))
    if plan_rows is not None:
        rows = [r for r in plan_rows if a.wave is None or int(r["wave"]) == a.wave]
        if not rows:
            waves = sorted({int(r["wave"]) for r in plan_rows})
            print(f"nocturne: warning: no segments in {a.plan}" + (f" for wave {a.wave}" if a.wave is not None else "")
                  + (f" (its waves: {', '.join(map(str, waves))})" if waves else ""), file=sys.stderr)
        out = os.path.join(a.out, f"assignments{'' if a.wave is None else '-wave' + str(a.wave)}.csv")
        with open(out, "w", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["segment", "ward", "road_class", "lights", "program", "switch_on"])
            for r in rows:
                w.writerow([r["segment"], r["ward"], r["road_class"], r["lights"], r["road_class"], r["switch_on"]])
        print(f"wrote {out}: {len(rows):,} segments", file=sys.stderr)
    print("wrote", os.path.join(a.out, "programs.json"), file=sys.stderr)
    return 0


def cmd_restore(a) -> int:
    from .restore import read_project, solve, format_plan
    result = solve(read_project(a.project), a.budget)
    if a.report:
        from .restoration_report import render
        with open(a.report, "x", encoding="utf-8") as stream:
            stream.write(render(result))
        print(f"wrote {a.report}", file=sys.stderr)
    print(json.dumps(result, indent=2, allow_nan=False) if a.json else format_plan(result))
    return 0 if result["status"] == "feasible" else 3


def cmd_experiment(a) -> int:
    from pathlib import Path
    from .attribution import make_trial, write_template
    trial = make_trial(a.source, a.start.isoformat(), a.seed, a.pairs, a.fraction, a.timezone, a.control_scale)
    directory = Path(a.out)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "trial.json").write_text(json.dumps(trial, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write_template(trial, directory / "readings.csv")
    print(json.dumps({"trial_sha256": trial["trial_sha256"], "nights": len(trial["sources"]) * trial["pairs"],
                      "out": str(directory), "status": "study design only; no lights controlled",
                      "next": "Review docs/RESTORATION.md, preregister trial.json, then fill readings.csv from screened observations."}, indent=2))
    return 0


def cmd_attribute(a) -> int:
    from .restore import read_project
    from .attribution import analyze
    result = analyze(read_project(a.trial), a.readings)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if all(e["complete"] and e["status"] != "insufficient_data" for e in result["estimates"]) else 3


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nocturne", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("restore", help="find the least-cost portfolio that meets every darkness target",
                        epilog="Exit 0: model targets met; 3: unmet targets; 2: invalid input. This is not a deployment approval.")
    rp.add_argument("project", help="restoration project JSON")
    rp.add_argument("--budget", type=_nonneg_float, help="override capital budget in USD")
    rp.add_argument("--report", help="write a portable HTML brief (new file only)")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(fn=cmd_restore)

    ex = sub.add_parser("experiment", help="preregister randomized source-isolation windows; no actuation")
    ex.add_argument("--source", action="append", required=True, help="consenting source group ID; repeat for several groups")
    ex.add_argument("--start", type=_iso_date, required=True, help="first evening YYYY-MM-DD")
    ex.add_argument("--seed", required=True, help="public seed fixed before collecting data")
    ex.add_argument("--pairs", type=_positive_int, default=12, help="6–64 nights per source; not a power calculation")
    ex.add_argument("--fraction", type=float, default=0.5, help="reviewed treatment light-output fraction, 0–0.95")
    ex.add_argument("--timezone", default="America/New_York", help="IANA timezone")
    ex.add_argument("--control-scale", type=float, default=1.0, help="preregistered additive control coefficient")
    ex.add_argument("--out", required=True, help="new trial directory (will not overwrite)")
    ex.set_defaults(fn=cmd_experiment)

    at = sub.add_parser("attribute", help="estimate source-specific effects from a preregistered crossover trial",
                        epilog="Exit 0: all planned pairs analyzed; 3: incomplete/insufficient data; 2: invalid input. Exit 0 does not imply an effect.")
    at.add_argument("trial", help="original trial.json")
    at.add_argument("readings", help="completed readings.csv")
    at.set_defaults(fn=cmd_attribute)

    t = sub.add_parser("trace", help="run one node on the bench and print its decisions")
    t.add_argument("--road", default="local", choices=[r.value for r in RoadClass])
    t.add_argument("--start", type=_local_time_text, default="2026-10-13 18:00", help="local time")
    t.add_argument("--end", type=_local_time_text, default="2026-10-14 08:00", help="local time")
    t.add_argument("--every", type=_positive_int, default=15, help="print a row every N minutes from --start")
    t.add_argument("--dt", type=_positive_float, default=5.0)
    t.add_argument("--hin", action="store_true")
    t.add_argument("--tunable", action="store_true")
    t.add_argument("--offline", action="store_true", help="never any backhaul")
    t.add_argument("--offline-at", type=_clock,
                   help="H:MM local at which the backhaul is lost (the first such time after --start)")
    t.add_argument("--event", action="append", type=_event,
                   help="kind@H:MM[:ttl_min[:level]], e.g. emergency@00:40:60 or override@23:00:120:50 "
                        "(the first such time after --start)")
    t.add_argument("--site", default="dc", choices=sorted(SITES), help="where the node is (latitude, longitude, DST rule)")
    t.set_defaults(fn=cmd_trace)

    s = sub.add_parser("spectral", help="print the spectral metrics table")
    s.add_argument("--json", action="store_true")
    s.add_argument("--spd", action="append", help="name=path.csv: add a measured spectrum (nm, power)")
    s.set_defaults(fn=cmd_spectral)

    m = sub.add_parser("simulate", help="run the network night simulation")
    m.add_argument("--out", default="out")
    m.add_argument("--dt", type=_positive_float, default=10.0)
    m.add_argument("--scenario", action="append")
    m.set_defaults(fn=cmd_simulate)

    k = sub.add_parser("keygen", help="create the CMS Ed25519 signing key")
    k.add_argument("--out", default="cms_key.pem")
    k.add_argument("--force", action="store_true")
    k.set_defaults(fn=cmd_keygen)

    bnd = sub.add_parser("bundle", help="sign the default profile bundle with the CMS key")
    bnd.add_argument("--key", required=True, help="PEM private key from `nocturne keygen`")
    bnd.add_argument("--version", type=int, default=1)
    bnd.add_argument("--issued", type=_iso_date_text, default="2026-10-13", help="ISO date; valid 400 days")
    bnd.add_argument("--zones", help="JSON {zone: {road_class: [5 phase levels]}} neighbourhood overlays")
    bnd.add_argument("--out")
    bnd.set_defaults(fn=cmd_bundle)

    bc = sub.add_parser("business-case", help="a year of energy, cost, carbon, light and skyglow")
    bc.add_argument("--site", default="dc", choices=sorted(SITES))
    bc.add_argument("--fleet", default="dc", choices=["dc", "spec"], help="DC's real fleet, or the Section 6.4 assumed one")
    bc.add_argument("--lights", type=_positive_int, default=75_000, help="fleet size for --fleet spec")
    bc.add_argument("--year", type=int, default=2027)
    bc.add_argument("--price", type=_nonneg_float, default=0.13, help="USD per kWh (ASSUMED)")
    bc.add_argument("--co2", type=_nonneg_float, default=0.30, help="tCO2 per MWh (ASSUMED)")
    bc.add_argument("--floor", type=_pct, default=50.0, help="Phase 0 floor for streets without presence sensing, %%")
    bc.add_argument("--json", action="store_true")
    bc.set_defaults(fn=cmd_business_case)

    sc = sub.add_parser("schedule", help="Phase 0: programmes for the existing networked nodes, per wave")
    sc.add_argument("--out", default="phase0", help="directory for programs.json and assignments")
    sc.add_argument("--floor", type=_pct, default=50.0, help="floor for streets without presence sensing, %%")
    sc.add_argument("--zones", help="JSON {zone: {road_class: [5 phase levels]}} neighbourhood overlays")
    sc.add_argument("--plan", help="the pilot plan CSV from `nocturne pilot --out`")
    sc.add_argument("--wave", type=_positive_int, help="only this wave's segments (needs --plan)")
    sc.add_argument("--site", default="dc", choices=sorted(SITES))
    sc.add_argument("--version", type=int, default=1, help="bundle version the programmes come from")
    sc.set_defaults(fn=cmd_schedule)

    sk = sub.add_parser("sky", help="zenith sky brightness and stars at DC's dark places")
    sk.add_argument("--share", type=float, default=0.15, help="streetlights' share of artificial light (Tucson prior)")
    sk.add_argument("--cut", type=float, default=0.5, help="Night Signal: share of other lighting cut after 23:00")
    sk.add_argument("--measured", action="append", help="place=msas from a sky quality meter, e.g. rock-creek=18.4")
    sk.add_argument("--place", action="append", help="limit to these place keys")
    sk.add_argument("--retrofits", type=_nonneg_int, default=0, help="also list the N best cells for globe retrofits")
    sk.add_argument("--json", action="store_true",
                    help="JSON: the rows, or {\"places\": rows, \"retrofits\": [...]} with --retrofits")
    sk.set_defaults(fn=cmd_sky)

    bg = sub.add_parser("bug", help="BUG rating and uplight of an IES LM-63 file")
    bg.add_argument("ies")
    bg.add_argument("--json", action="store_true")
    bg.set_defaults(fn=cmd_bug)

    tr = sub.add_parser("trespass", help="light on a bedroom window through the night")
    tr.add_argument("ies")
    tr.add_argument("--height", type=_positive_float, default=9.0, help="mounting height, m")
    tr.add_argument("--setback", type=_nonneg_float, default=10.0, help="window distance behind the pole, m")
    tr.add_argument("--window", type=_nonneg_float, default=5.0, help="window height, m")
    tr.add_argument("--road", default="local", choices=[r.value for r in RoadClass])
    tr.add_argument("--spectrum", default="2700K", choices=["4000K", "3000K", "2700K", "2200K", "PC-Amber"])
    tr.add_argument("--tunable", action="store_true", help="amber channel in the curfew and deep phases")
    tr.add_argument("--zone", default="E3", choices=["E1", "E2", "E3", "E4"], help="CIE 150 environmental zone")
    tr.set_defaults(fn=cmd_trespass)

    sg = sub.add_parser("signal", help="tonight's Night Signal (JSON, optionally signed; iCal feed)")
    sg.add_argument("--date", type=_iso_date, help="the evening, YYYY-MM-DD (default today)")
    sg.add_argument("--site", default="dc", choices=sorted(SITES))
    sg.add_argument("--migration", action="store_true", help="heavy migration forecast tonight")
    sg.add_argument("--migration-source", default="BirdCast")
    sg.add_argument("--key", help="PEM key to sign with")
    sg.add_argument("--ics", help="also write an iCalendar feed here")
    sg.add_argument("--days", type=_positive_int, default=1, help="nights in the iCalendar feed")
    sg.set_defaults(fn=cmd_signal)

    vf = sub.add_parser("verify", help="before/after evidence from a sky quality meter log")
    vf.add_argument("log")
    vf.add_argument("--go-live", type=_iso_date, required=True, help="first night of the new lighting, YYYY-MM-DD")
    vf.add_argument("--site", default="dc", choices=sorted(SITES))
    vf.set_defaults(fn=cmd_verify)

    pl = sub.add_parser("pilot", help="randomised stepped-wedge rollout over DC's street segments")
    pl.add_argument("--seed", help="public text fixed before the draw")
    pl.add_argument("--waves", type=_positive_int, default=4)
    pl.add_argument("--start", type=_iso_date, default="2027-01-04")
    pl.add_argument("--wave-days", type=_positive_int, default=56)
    pl.add_argument("--segments", help="CSV segment,ward,road_class,lights,kw (default: DC's)")
    pl.add_argument("--out", help="write the plan as CSV")
    pl.add_argument("--power", nargs=2, type=_positive_float, metavar=("RATE", "RR"),
                    help="segment-nights needed instead of a plan (RR other than 1)")
    pl.set_defaults(fn=cmd_pilot)

    bk = sub.add_parser("brake", help="the pilot's safety check before each wave",
                        epilog="Exit status: 0 continue; 2 pause. Bad input also exits non-zero, so a script "
                               "should start the next wave only on 0.")
    bk.add_argument("--plan", required=True, help="the plan CSV from `nocturne pilot --out`")
    bk.add_argument("--crashes", required=True, help="CSV segment,night (YYYY-MM-DD: the evening the night began)")
    bk.add_argument("--through", type=_iso_date, required=True, help="last night counted, YYYY-MM-DD")
    bk.add_argument("--looks", type=_positive_int, help="looks the error rate is split over (default: waves - 1)")
    bk.set_defaults(fn=cmd_brake)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except BrokenPipeError:                         # `nocturne trace | head`: stop quietly
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass
        return 1
    except (OSError, ValueError) as e:              # bad input: a message, not a traceback (argparse's code)
        print(f"nocturne: error: {_describe(e)}", file=sys.stderr)
        return 2


def _describe(e: Exception) -> str:
    if isinstance(e, OSError) and e.filename and e.strerror:
        return f"{e.filename}: {e.strerror}"
    return str(e) or type(e).__name__


if __name__ == "__main__":
    sys.exit(main())
