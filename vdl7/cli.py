"""`nocturne` command line.

    nocturne trace --road local --from "2026-10-13 18:00" --to "2026-10-14 08:00"
    nocturne trace --road arterial --offline-at 22:00 --event emergency@00:40:60
    nocturne spectral
    nocturne simulate --out out
    nocturne bundle --version 2 --out bundle.json      # sign a profile bundle
"""
from __future__ import annotations

import argparse
import base64
import json
import sys

from .bench import Bench
from .events import EventKind, Priority
from .profiles import RoadClass, default_bundle
from .security import make_signer
from . import spectral


def cmd_trace(a) -> int:
    b = Bench(RoadClass(a.road), start=a.start, hin=a.hin, tunable=a.tunable, online=not a.offline)
    events = []
    for spec in a.event or []:
        kind, _, rest = spec.partition("@")
        parts = rest.split(":")
        at = f"{parts[0]}:{parts[1]}"
        ttl_min = int(parts[2]) if len(parts) > 2 else 60
        level = int(parts[3]) if len(parts) > 3 else None
        events.append((kind, at, ttl_min, level))
    offline_at = a.offline_at
    print(f"{'local':6s} {'mode':10s} {'phase':8s} {'lit':3s} {'base':>4s} {'act':>4s} {'target':>6s} {'level':>5s} {'white':>5s} {'amber':>5s}  reasons")
    last_minute = None
    end = a.end
    day = a.start[:10]
    from .clock import parse_local, to_local
    end_utc = parse_local(end)
    fired = set()
    while b.utc < end_utc:
        loc = b.local
        hhmm = loc.strftime("%H:%M")
        if offline_at and hhmm == offline_at and "off" not in fired:
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
        minute = loc.minute // a.every * a.every
        key = (loc.hour, minute)
        if key != last_minute and loc.minute % a.every == 0:
            last_minute = key
            print(f"{hhmm:6s} {out.mode.value:10s} {out.phase.value:8s} {'y' if out.lit else '-':3s} {out.base:4d} "
                  f"{out.activity:4.2f} {out.target:6.1f} {out.level:5.1f} {out.white:5.1f} {out.amber:5.1f}  "
                  f"{' '.join(out.reasons[2:])}")
    return 0


def cmd_spectral(a) -> int:
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
    if a.quiet:
        argv.append("--quiet")
    return sim_main(argv)


def cmd_bundle(a) -> int:
    signer = make_signer()
    bundle = default_bundle(version=a.version)
    msg = signer.sign_obj(bundle.to_dict())
    doc = {"payload": msg.payload.decode(), "signature_b64": base64.b64encode(msg.signature).decode(),
           "note": "Ed25519 (or bench HMAC) signature over the canonical payload bytes"}
    text = json.dumps(doc, indent=2)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text)
        print("wrote", a.out)
    else:
        print(text)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nocturne", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("trace", help="run one node on the bench and print its decisions")
    t.add_argument("--road", default="local", choices=[r.value for r in RoadClass])
    t.add_argument("--start", dest="start", default="2026-10-13 18:00")
    t.add_argument("--end", dest="end", default="2026-10-14 08:00")
    t.add_argument("--every", type=int, default=15, help="print every N minutes")
    t.add_argument("--dt", type=float, default=5.0)
    t.add_argument("--hin", action="store_true")
    t.add_argument("--tunable", action="store_true")
    t.add_argument("--offline", action="store_true", help="never any backhaul")
    t.add_argument("--offline-at", help="HH:MM local at which the backhaul is lost")
    t.add_argument("--event", action="append", help="kind@HH:MM[:ttl_min[:level]], e.g. emergency@00:40:60 or override@23:00:120:50")
    t.set_defaults(fn=cmd_trace)

    s = sub.add_parser("spectral", help="print the spectral metrics table")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_spectral)

    m = sub.add_parser("simulate", help="run the network night simulation")
    m.add_argument("--out", default="out")
    m.add_argument("--dt", type=float, default=10.0)
    m.add_argument("--scenario", action="append")
    m.add_argument("--quiet", action="store_true")
    m.set_defaults(fn=cmd_simulate)

    bnd = sub.add_parser("bundle", help="sign a profile bundle for distribution")
    bnd.add_argument("--version", type=int, default=1)
    bnd.add_argument("--out")
    bnd.set_defaults(fn=cmd_bundle)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
