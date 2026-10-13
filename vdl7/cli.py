"""`nocturne` command line.

    nocturne trace --road local
    nocturne trace --road arterial --offline-at 22:00 --event emergency@00:40:60
    nocturne spectral [--spd my_engine=lm79.csv]
    nocturne simulate --out out
    nocturne keygen --out cms_key.pem                      # CMS signing key, prints the node public key
    nocturne bundle --key cms_key.pem --version 2 --out bundle.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys

from . import spectral
from .bench import Bench
from .clock import parse_local
from .events import EventKind, Priority
from .profiles import RoadClass, default_bundle, validate_bundle
from .security import Ed25519Signer


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
    print(f"{'local':6s} {'mode':10s} {'phase':8s} {'lit':3s} {'base':>4s} {'act':>4s} {'target':>6s} "
          f"{'level':>5s} {'white':>5s} {'amber':>5s}  reasons")
    end_utc = parse_local(a.end)
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
    bnd.add_argument("--out")
    bnd.set_defaults(fn=cmd_bundle)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
