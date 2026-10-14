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
    nocturne spectral [--spd my_engine=lm79.csv]
    nocturne simulate --out out
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import date, timedelta

from . import spectral
from .bench import Bench
from .clock import parse_local
from .events import EventKind, Priority
from .profiles import PHASE_ORDER, RoadClass, default_bundle, validate_bundle
from .security import Ed25519Signer
from .sites import SITES, site


def cmd_trace(a) -> int:
    b = Bench(RoadClass(a.road), start=a.start, hin=a.hin, tunable=a.tunable, online=not a.offline,
              site=site(a.site))
    events = []
    for spec in a.event or []:
        kind, _, rest = spec.partition("@")
        parts = rest.split(":")
        at = f"{parts[0]}:{parts[1]}"
        ttl_min = int(parts[2]) if len(parts) > 2 else 60
        level = int(parts[3]) if len(parts) > 3 else None
        events.append((kind, at, ttl_min, level))
    print(f"{'local':6s} {'mode':10s} {'phase':8s} {'lit':3s} {'base':>4s} {'act':>4s} {'target':>6s} "
          f"{'level':>5s} {'white':>5s} {'amber':>5s}  reasons")
    end_utc = parse_local(a.end, b.site.tz)
    last_key, fired = None, set()
    while b.utc < end_utc:
        loc = b.local
        hhmm = loc.strftime("%H:%M")
        if a.offline_at and hhmm == a.offline_at and "off" not in fired:
            b.go_offline()
            fired.add("off")
            print(f"--- backhaul lost at {hhmm}")
        for i, (kind, at, ttl_min, level) in enumerate(events):
            if hhmm == at and i not in fired:
                k = EventKind(kind)
                payload = {"level": level} if level is not None else {}
                prio = Priority.OPERATOR if k == EventKind.OVERRIDE else Priority.NONE
                via = "backhaul" if b.online else "mesh"
                b.send(k, ttl_min * 60, payload, prio, via=via)
                fired.add(i)
                print(f"--- event {kind} at {hhmm} via {via}, ttl {ttl_min} min")
        out = b.step(a.dt)
        key = (loc.hour, loc.minute // a.every)
        if key != last_key and loc.minute % a.every == 0:
            last_key = key
            print(f"{hhmm:6s} {out.mode.value:10s} {out.phase.value:8s} {'y' if out.lit else '-':3s} {out.base:4d} "
                  f"{out.activity:4.2f} {out.target:6.1f} {out.level:5.1f} {out.white:5.1f} {out.amber:5.1f}  "
                  f"{' '.join(out.reasons[2:] + list(out.alarms))}")
    return 0


def cmd_spectral(a) -> int:
    for item in a.spd or []:
        name, _, path = item.partition("=")
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
    from sim.run_night import main as sim_main
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
    print(f"wrote private key {a.out} (mode 600): keep it on the CMS signing host only")
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
        print("wrote", a.out)
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
    fleet = dc_fleet()
    cct = {c: fleet.classes[c].mix() for c in CLASSES}
    measured = {}
    for item in a.measured or []:
        k, _, v = item.partition("=")
        measured[k] = float(v)
    places = [p for p in PLACES_DC if not a.place or p.key in a.place]
    cells = load_grid()
    rows = sky_scenarios(cells, places, cct, share=a.share, other_curfew_cut=a.cut, measured=measured or None)
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        print(format_sky(rows))
    if a.retrofits:
        print("\nPost-top globes to fix first (top reflectors), ranked by sky regained at these places per kW:")
        for s in plan_retrofits(cells, places, lighting_for("phase1", 1.5, cct), top=a.retrofits):
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
    first = date.fromisoformat(a.date) if a.date else date.today()
    mig = {"source": a.migration_source} if a.migration else None
    docs = [signal(first + timedelta(days=i), site=s, migration=mig if i == 0 else None)
            for i in range(max(1, a.days))]
    if a.ics:
        with open(a.ics, "w", newline="") as f:
            f.write(to_ics(docs))
        print(f"wrote {a.ics}: {len(docs)} nights")
    out = docs[0]
    if a.key:
        with open(a.key, "rb") as f:
            out = sign(out, Ed25519Signer.from_pem(f.read()))
    print(json.dumps(out, indent=2))
    return 0


def cmd_verify(a) -> int:
    from .observe import read_sqm, verify
    s = site(a.site)
    r = verify(read_sqm(a.log), date.fromisoformat(a.go_live), s.lat, s.lon, s.tz)
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
        rate, rr = float(a.power[0]), float(a.power[1])
        n = exposure_needed(rate, rr)
        print(f"{n:,.0f} segment-nights per arm to detect a rate ratio of {rr:g} on a baseline of {rate:g} "
              f"events per segment-night (two-sided 5 %, 80 % power)")
        return 0
    if not a.seed:
        print("--seed is required: a string published before the draw", file=sys.stderr)
        return 1
    segs = load_segments(a.segments) if a.segments else load_segments()
    plan = stepped_wedge(segs, a.seed, waves=a.waves, start=date.fromisoformat(a.start), wave_days=a.wave_days)
    for w in range(1, plan.waves + 1):
        n = sum(1 for v in plan.assignment.values() if v == w)
        lights = sum(sg.lights for sg in segs if plan.assignment[sg.id] == w)
        print(f"wave {w}: {n:,} segments, {lights:,} lights, switch on {plan.wave_start(w).isoformat()}")
    if a.out:
        plan.to_csv(a.out, segs)
        print("wrote", a.out)
    return 0


def _zones_from(path):
    """Zone overlays from JSON, read by the bundle's own strict parser: a
    level of 80.9 or 100.9 is refused, never rounded into a valid one."""
    from .profiles import ProfileBundle
    with open(path) as f:
        raw = json.load(f)
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


def cmd_brake(a) -> int:
    import csv
    from .pilot import brake, tally
    with open(a.plan) as f:
        rows = list(csv.DictReader(f))
    switch_on = {r["segment"]: date.fromisoformat(r["switch_on"]) for r in rows}
    waves = len({r["wave"] for r in rows})
    with open(a.crashes) as f:
        events = [(r["segment"], date.fromisoformat(r["night"])) for r in csv.DictReader(f)]
    periods, skipped = tally(switch_on, events, date.fromisoformat(a.through))
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
    import csv
    from .schedule import export, programs
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
    if a.plan:
        with open(a.plan) as f:
            rows = [r for r in csv.DictReader(f) if a.wave is None or int(r["wave"]) == a.wave]
        out = os.path.join(a.out, f"assignments{'' if a.wave is None else '-wave' + str(a.wave)}.csv")
        with open(out, "w") as f:
            f.write("segment,ward,road_class,lights,program,switch_on\n")
            for r in rows:
                f.write(f"{r['segment']},{r['ward']},{r['road_class']},{r['lights']},{r['road_class']},{r['switch_on']}\n")
        print(f"wrote {out}: {len(rows):,} segments")
    print("wrote", os.path.join(a.out, "programs.json"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nocturne", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("trace", help="run one node on the bench and print its decisions")
    t.add_argument("--road", default="local", choices=[r.value for r in RoadClass])
    t.add_argument("--start", default="2026-10-13 18:00", help="local time")
    t.add_argument("--end", default="2026-10-14 08:00", help="local time")
    t.add_argument("--every", type=int, default=15, help="print every N minutes")
    t.add_argument("--dt", type=float, default=5.0)
    t.add_argument("--hin", action="store_true")
    t.add_argument("--tunable", action="store_true")
    t.add_argument("--offline", action="store_true", help="never any backhaul")
    t.add_argument("--offline-at", help="HH:MM local at which the backhaul is lost")
    t.add_argument("--event", action="append",
                   help="kind@HH:MM[:ttl_min[:level]], e.g. emergency@00:40:60 or override@23:00:120:50")
    t.add_argument("--site", default="dc", choices=sorted(SITES), help="where the node is (latitude, longitude, DST rule)")
    t.set_defaults(fn=cmd_trace)

    s = sub.add_parser("spectral", help="print the spectral metrics table")
    s.add_argument("--json", action="store_true")
    s.add_argument("--spd", action="append", help="name=path.csv: add a measured spectrum (nm, power)")
    s.set_defaults(fn=cmd_spectral)

    m = sub.add_parser("simulate", help="run the network night simulation")
    m.add_argument("--out", default="out")
    m.add_argument("--dt", type=float, default=10.0)
    m.add_argument("--scenario", action="append")
    m.set_defaults(fn=cmd_simulate)

    k = sub.add_parser("keygen", help="create the CMS Ed25519 signing key")
    k.add_argument("--out", default="cms_key.pem")
    k.add_argument("--force", action="store_true")
    k.set_defaults(fn=cmd_keygen)

    bnd = sub.add_parser("bundle", help="sign the default profile bundle with the CMS key")
    bnd.add_argument("--key", required=True, help="PEM private key from `nocturne keygen`")
    bnd.add_argument("--version", type=int, default=1)
    bnd.add_argument("--issued", default="2026-10-13", help="ISO date; valid 400 days")
    bnd.add_argument("--zones", help="JSON {zone: {road_class: [5 phase levels]}} neighbourhood overlays")
    bnd.add_argument("--out")
    bnd.set_defaults(fn=cmd_bundle)

    bc = sub.add_parser("business-case", help="a year of energy, cost, carbon, light and skyglow")
    bc.add_argument("--site", default="dc", choices=sorted(SITES))
    bc.add_argument("--fleet", default="dc", choices=["dc", "spec"], help="DC's real fleet, or the Section 6.4 assumed one")
    bc.add_argument("--lights", type=int, default=75_000, help="fleet size for --fleet spec")
    bc.add_argument("--year", type=int, default=2027)
    bc.add_argument("--price", type=float, default=0.13, help="USD per kWh (ASSUMED)")
    bc.add_argument("--co2", type=float, default=0.30, help="tCO2 per MWh (ASSUMED)")
    bc.add_argument("--floor", type=_pct, default=50.0, help="Phase 0 floor for streets without presence sensing, %%")
    bc.add_argument("--json", action="store_true")
    bc.set_defaults(fn=cmd_business_case)

    sc = sub.add_parser("schedule", help="Phase 0: programmes for the existing networked nodes, per wave")
    sc.add_argument("--out", default="phase0", help="directory for programs.json and assignments")
    sc.add_argument("--floor", type=_pct, default=50.0, help="floor for streets without presence sensing, %%")
    sc.add_argument("--zones", help="JSON {zone: {road_class: [5 phase levels]}} neighbourhood overlays")
    sc.add_argument("--plan", help="the pilot plan CSV from `nocturne pilot --out`")
    sc.add_argument("--wave", type=int, help="only this wave's segments")
    sc.add_argument("--site", default="dc", choices=sorted(SITES))
    sc.add_argument("--version", type=int, default=1, help="bundle version the programmes come from")
    sc.set_defaults(fn=cmd_schedule)

    sk = sub.add_parser("sky", help="zenith sky brightness and stars at DC's dark places")
    sk.add_argument("--share", type=float, default=0.15, help="streetlights' share of artificial light (Tucson prior)")
    sk.add_argument("--cut", type=float, default=0.5, help="Night Signal: share of other lighting cut after 23:00")
    sk.add_argument("--measured", action="append", help="place=msas from a sky quality meter, e.g. rock-creek=18.4")
    sk.add_argument("--place", action="append", help="limit to these place keys")
    sk.add_argument("--retrofits", type=int, default=0, help="also list the N best cells for globe retrofits")
    sk.add_argument("--json", action="store_true")
    sk.set_defaults(fn=cmd_sky)

    bg = sub.add_parser("bug", help="BUG rating and uplight of an IES LM-63 file")
    bg.add_argument("ies")
    bg.add_argument("--json", action="store_true")
    bg.set_defaults(fn=cmd_bug)

    tr = sub.add_parser("trespass", help="light on a bedroom window through the night")
    tr.add_argument("ies")
    tr.add_argument("--height", type=float, default=9.0, help="mounting height, m")
    tr.add_argument("--setback", type=float, default=10.0, help="window distance behind the pole, m")
    tr.add_argument("--window", type=float, default=5.0, help="window height, m")
    tr.add_argument("--road", default="local", choices=[r.value for r in RoadClass])
    tr.add_argument("--spectrum", default="2700K", choices=["4000K", "3000K", "2700K", "2200K", "PC-Amber"])
    tr.add_argument("--tunable", action="store_true", help="amber channel in the curfew and deep phases")
    tr.add_argument("--zone", default="E3", choices=["E1", "E2", "E3", "E4"], help="CIE 150 environmental zone")
    tr.set_defaults(fn=cmd_trespass)

    sg = sub.add_parser("signal", help="tonight's Night Signal (JSON, optionally signed; iCal feed)")
    sg.add_argument("--date", help="the evening, YYYY-MM-DD (default today)")
    sg.add_argument("--site", default="dc", choices=sorted(SITES))
    sg.add_argument("--migration", action="store_true", help="heavy migration forecast tonight")
    sg.add_argument("--migration-source", default="BirdCast")
    sg.add_argument("--key", help="PEM key to sign with")
    sg.add_argument("--ics", help="also write an iCalendar feed here")
    sg.add_argument("--days", type=int, default=1, help="nights in the iCalendar feed")
    sg.set_defaults(fn=cmd_signal)

    vf = sub.add_parser("verify", help="before/after evidence from a sky quality meter log")
    vf.add_argument("log")
    vf.add_argument("--go-live", required=True, help="first night of the new lighting, YYYY-MM-DD")
    vf.add_argument("--site", default="dc", choices=sorted(SITES))
    vf.set_defaults(fn=cmd_verify)

    pl = sub.add_parser("pilot", help="randomised stepped-wedge rollout over DC's street segments")
    pl.add_argument("--seed", help="public text fixed before the draw")
    pl.add_argument("--waves", type=int, default=4)
    pl.add_argument("--start", default="2027-01-04")
    pl.add_argument("--wave-days", type=int, default=56)
    pl.add_argument("--segments", help="CSV segment,ward,road_class,lights,kw (default: DC's)")
    pl.add_argument("--out", help="write the plan as CSV")
    pl.add_argument("--power", nargs=2, metavar=("RATE", "RR"), help="segment-nights needed instead of a plan")
    pl.set_defaults(fn=cmd_pilot)

    bk = sub.add_parser("brake", help="the pilot's safety check before each wave")
    bk.add_argument("--plan", required=True, help="the plan CSV from `nocturne pilot --out`")
    bk.add_argument("--crashes", required=True, help="CSV segment,night (YYYY-MM-DD: the evening the night began)")
    bk.add_argument("--through", required=True, help="last night counted, YYYY-MM-DD")
    bk.add_argument("--looks", type=int, help="looks the error rate is split over (default: waves - 1)")
    bk.set_defaults(fn=cmd_brake)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
