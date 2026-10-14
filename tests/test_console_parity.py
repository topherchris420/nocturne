"""The operator console re-implements the control loop in JavaScript. This
runs the console's controller block in Node.js and the Python controller
through the same night, input for input, and requires the same output at
every 10-second tick: light level, driver drive (constant light output),
white and amber channels, mode and phase. Skipped where Node.js is not
installed.

The console's fleet sits at 20,000 burn hours at dusk, so the Python nodes
are commissioned at 20,000 h too. Console nodes start with a trusted clock
(set at commissioning or by GNSS), so every Python node gets a GNSS fix at
18:00 before the first tick. The console's SAFE mode counts from a dark
midpoint learned on the previous clocked night, so the SAFE scenarios first
run the Python node through the night before (12-13 Oct) on a trusted clock.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import timedelta

import pytest

from vdl7.bench import Bench
from vdl7.events import EventKind, Priority
from vdl7.profiles import RoadClass

ROOT = os.path.join(os.path.dirname(__file__), "..")
NODE = shutil.which("node")
DT, T_END = 10, 50400
BURN_HOURS = 20000.0          # BURN_HOURS0 in console/index.html
NIGHT = "2026-10-13 18:00"
SCENARIOS = [
    {"name": "arterial", "cls": "arterial", "veh15": 150},
    {"name": "collector", "cls": "collector", "veh15": 60},
    {"name": "local", "cls": "local"},
    {"name": "alley", "cls": "alley"},
    {"name": "park", "cls": "park"},
    {"name": "local-rain", "cls": "local", "events": [{"t": 18000, "kind": "rain", "ttl": 1800}]},
    {"name": "park-migration", "cls": "park", "events": [{"t": 0, "kind": "migration", "ttl": 50400}]},
    {"name": "alley-emergency", "cls": "alley", "events": [{"t": 27000, "kind": "emergency", "ttl": 600}]},
    {"name": "local-override", "cls": "local",
     "events": [{"t": 28800, "kind": "override", "ttl": 1800, "level": 50, "priority": 2}]},
    # only incident command pulls an emergency below 100 %
    {"name": "alley-emergency-ic-override", "cls": "alley",
     "events": [{"t": 27000, "kind": "emergency", "ttl": 3600},
                {"t": 27600, "kind": "override", "ttl": 1800, "level": 5, "priority": 3}]},
    # tunable white: the white/amber mix follows the phase, presence turns it white
    {"name": "collector-tunable", "cls": "collector", "veh15": 60, "tunable": True},
    {"name": "local-tunable-presence", "cls": "local", "tunable": True, "presence": [16000, 27000, 40000]},
    # carrier outage from 22:30: hellos stop, the node runs AUTONOMOUS on its own clock
    {"name": "local-outage", "cls": "local", "hello_stop": 16200},
    {"name": "arterial-outage", "cls": "arterial", "veh15": 150, "hello_stop": 16200},   # loop count expires with its TTL
    # modem fault: no backhaul all night, but the clock is good. With a mesh path to a gateway the node runs MESH
    # and still gets the CMS's events relayed; with none it runs AUTONOMOUS. Neither is SAFE.
    {"name": "local-modem-mesh", "cls": "local", "hello_stop": 0, "mesh": True,
     "events": [{"t": 27000, "kind": "emergency", "ttl": 600, "via": "mesh"}]},
    {"name": "collector-modem-isolated", "cls": "collector", "veh15": 60, "hello_stop": 0},
    # clock lost (SAFE) with no backhaul to resync it: the night-hour comes from the photocell dusk
    {"name": "local-safe", "cls": "local", "clock_loss": 16200, "warmup": True},
    {"name": "arterial-safe", "cls": "arterial", "veh15": 150, "clock_loss": 16200, "warmup": True},
    {"name": "alley-safe-early", "cls": "alley", "clock_loss": 7200, "warmup": True},
]
KIND = {"rain": EventKind.RAIN, "migration": EventKind.MIGRATION, "emergency": EventKind.EMERGENCY,
        "override": EventKind.OVERRIDE}
FIELDS = ("level", "drive", "white", "amber", "mode", "phase")

DRIVER = """
const SCN = %s;
const out = {};
for (const sc of SCN) {
  const cls = CLASSES.find(c => c.id === sc.cls);
  const n = new Node(cls, 1);
  n.tunable = !!sc.tunable;
  const rec = { level: [], drive: [], white: [], amber: [], mode: [], phase: [] };
  for (let t = 0; t <= T_END; t += DT) {
    const helloOk = !(sc.clock_loss !== undefined && t >= sc.clock_loss) && !(sc.hello_stop !== undefined && t >= sc.hello_stop);
    if (t %% 900 === 0 && helloOk) { n.hello(t); if (cls.vol) n.receive({ kind: 'loop', id: 'loop', ttl: 900, veh15: sc.veh15 || 0 }, t); }
    if (sc.clock_loss === t) n.rtcTrusted = false;
    for (const ev of (sc.events || [])) if (ev.t === t) n.receive(Object.assign({ id: ev.kind + '-' + t }, ev), t);
    if ((sc.presence || []).includes(t)) n.presenceUntil = t + 90;
    if (sc.mesh) n.lastGateway = t;
    n.photocell(skyLux(elevAt(t)), t);
    const o = n.tick(t, DT, null);
    for (const f of Object.keys(rec)) rec[f].push(o[f]);
  }
  out[sc.name] = rec;
}
console.log(JSON.stringify(out));
"""


def _js_runs():
    with open(os.path.join(ROOT, "console", "index.html")) as f:
        html = f.read()
    m = re.search(r"// <controller>[^\n]*\n(.*?)// </controller>", html, re.S)
    assert m, "controller markers missing from console/index.html"
    script = "'use strict';\n" + m.group(1) + DRIVER % json.dumps(SCENARIOS)
    res = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=600)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def _step(b: Bench, hello: bool, veh15: float = 0.0) -> None:
    if hello:
        b.node.backhaul_hello(b.mono, b.utc)
        if veh15:
            b.loop_volume(veh15)


def _py_run(sc):
    start = NIGHT
    if sc.get("warmup"):
        start = "2026-10-12 18:00"
    b = Bench(RoadClass(sc["cls"]), start=start, tunable=bool(sc.get("tunable")), burn_hours=BURN_HOURS)
    if sc.get("warmup"):
        # the night before, on a trusted clock: the node learns its photocell night
        for k in range(86400 // DT):
            _step(b, (k * DT) % 900 == 0, sc.get("veh15", 0))
            b.node.photocell_sample(b.lx_now(), b.mono)
            b.node.tick(b.mono, DT)
            b.mono += DT
            b.utc += timedelta(seconds=DT)
        b.cfg.burn_hours = BURN_HOURS      # same hour meter as the console at dusk
    rec = {f: [] for f in FIELDS}
    for k in range(T_END // DT + 1):
        t = k * DT
        hello_ok = not (sc.get("clock_loss") is not None and t >= sc["clock_loss"]) and not (
            sc.get("hello_stop") is not None and t >= sc["hello_stop"])
        if t == 0:
            b.node.gnss_fix(b.mono, b.utc)  # the console's nodes start with a trusted clock
        _step(b, t % 900 == 0 and hello_ok, sc.get("veh15", 0))
        if sc.get("clock_loss") == t:
            b.rtc.reset()                  # wall time lost; no hello comes to resync it
        for ev in sc.get("events", []):
            if ev["t"] == t:
                payload = {"level": ev["level"]} if "level" in ev else {}
                b.send(KIND[ev["kind"]], ev["ttl"], payload, priority=ev.get("priority", Priority.NONE),
                       via=ev.get("via"))
        if t in sc.get("presence", []):
            b.node.radar_detect(b.mono)
        if sc.get("mesh"):
            b.node.mesh_gateway_seen(b.mono)
        b.node.photocell_sample(b.lx_now(), b.mono)
        out = b.node.tick(b.mono, DT)
        for f, v in zip(FIELDS, (out.level, out.drive, out.white, out.amber, out.mode.value, out.phase.value)):
            rec[f].append(v)
        b.mono += DT
        b.utc += timedelta(seconds=DT)
    return rec


def _hhmmss(t: int) -> str:
    return f"{(18 + t // 3600) % 24:02d}:{t // 60 % 60:02d}:{t % 60:02d}"


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_EXT_UI_1_console_controller_matches_python_tick_for_tick():
    js = _js_runs()
    for sc in SCENARIOS:
        py = _py_run(sc)
        for f in FIELDS:
            for k, (a, b) in enumerate(zip(js[sc["name"]][f], py[f])):
                ok = a == b if isinstance(b, str) else a == pytest.approx(b, abs=1e-6)
                assert ok, f"{sc['name']} {f} at {_hhmmss(k * DT)}: console {a!r}, python {b!r}"

    def lv(name, t):
        return js[name]["level"][t // DT]
    # and the scenarios are not trivially equal: rain, migration, emergency, override, SAFE and tunable all show
    assert lv("local-rain", 18300) > lv("local", 18300)
    assert lv("park-migration", 3600) < lv("park", 3600)
    assert lv("alley-emergency", 27010) > lv("alley", 27010)
    assert lv("local-override", 29400) == 50
    assert lv("alley-emergency-ic-override", 28800) == 5
    assert js["local-safe"]["mode"][19800 // DT] == "SAFE" and js["local-outage"]["mode"][19800 // DT] == "AUTONOMOUS"
    assert set(js["local-modem-mesh"]["mode"]) == {"MESH"} and lv("local-modem-mesh", 27010) == 100
    assert set(js["collector-modem-isolated"]["mode"]) == {"AUTONOMOUS"}
    assert max(js["collector-tunable"]["amber"]) > 0 and js["arterial"]["drive"][3600 // DT] < 100
