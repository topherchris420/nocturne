"""The operator console re-implements the control loop in JavaScript. This
runs the console's controller block in Node.js and the Python controller
through the same night, input for input, and requires the same light level
at every checkpoint. Skipped where Node.js is not installed.
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
CHECKS = [2400, 3600, 5400, 12600, 14700, 16200, 18300, 19800, 25500, 27010, 27600, 27700, 28800, 29400,
          30600, 37800, 39900, 43200, 46800, 48600]
SCENARIOS = [
    {"name": "arterial", "cls": "arterial", "veh15": 150, "events": []},
    {"name": "collector", "cls": "collector", "veh15": 60, "events": []},
    {"name": "local", "cls": "local", "veh15": 0, "events": []},
    {"name": "alley", "cls": "alley", "veh15": 0, "events": []},
    {"name": "park", "cls": "park", "veh15": 0, "events": []},
    {"name": "local-rain", "cls": "local", "veh15": 0, "events": [{"t": 18000, "kind": "rain", "ttl": 1800}]},
    {"name": "park-migration", "cls": "park", "veh15": 0, "events": [{"t": 0, "kind": "migration", "ttl": 50400}]},
    {"name": "alley-emergency", "cls": "alley", "veh15": 0, "events": [{"t": 27000, "kind": "emergency", "ttl": 600}]},
    {"name": "local-override", "cls": "local", "veh15": 0,
     "events": [{"t": 28800, "kind": "override", "ttl": 1800, "level": 50, "priority": 2}]},
]
KIND = {"rain": EventKind.RAIN, "migration": EventKind.MIGRATION, "emergency": EventKind.EMERGENCY,
        "override": EventKind.OVERRIDE}

DRIVER = """
const SCN = %s, CHECKS = %s;
const out = {};
for (const sc of SCN) {
  const cls = CLASSES.find(c => c.id === sc.cls);
  const n = new Node(cls, 1);
  const levels = {};
  for (let t = 0; t <= T_END; t += DT) {
    if (t %% 900 === 0) { n.hello(t); if (cls.vol) n.receive({ kind: 'loop', id: 'loop', ttl: 900, veh15: sc.veh15 }, t); }
    for (const ev of sc.events) if (ev.t === t) n.receive(Object.assign({ id: ev.kind + '-' + t }, ev), t);
    n.photocell(skyLux(elevAt(t)), t);
    const o = n.tick(t, DT, null);
    if (CHECKS.includes(t)) levels[t] = o.level;
  }
  out[sc.name] = levels;
}
console.log(JSON.stringify(out));
"""


def _js_levels():
    with open(os.path.join(ROOT, "console", "index.html")) as f:
        html = f.read()
    m = re.search(r"// <controller>[^\n]*\n(.*?)// </controller>", html, re.S)
    assert m, "controller markers missing from console/index.html"
    script = "'use strict';\n" + m.group(1) + DRIVER % (json.dumps(SCENARIOS), json.dumps(CHECKS))
    res = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def _py_levels(sc):
    b = Bench(RoadClass(sc["cls"]), start="2026-10-13 18:00")
    levels = {}
    for k in range(T_END // DT + 1):
        t = k * DT
        if t % 900 == 0:
            b.node.backhaul_hello(b.mono, b.utc)
            if sc["veh15"]:
                b.loop_volume(sc["veh15"])
        for ev in sc["events"]:
            if ev["t"] == t:
                payload = {"level": ev["level"]} if "level" in ev else {}
                b.send(KIND[ev["kind"]], ev["ttl"], payload, priority=ev.get("priority", Priority.NONE))
        b.node.photocell_sample(b.lx_now(), b.mono)
        out = b.node.tick(b.mono, DT)
        if t in CHECKS:
            levels[str(t)] = out.level
        b.mono += DT
        b.utc += timedelta(seconds=DT)
    return levels


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_EXT_UI_1_console_controller_matches_python_level_for_level():
    js = _js_levels()
    for sc in SCENARIOS:
        py = _py_levels(sc)
        for t in CHECKS:
            assert js[sc["name"]][str(t)] == pytest.approx(py[str(t)], abs=1e-6), (sc["name"], t)
    # and the scenarios are not trivially equal: rain, migration, emergency and override all show
    assert js["local-rain"]["18300"] > js["local"]["18300"]
    assert js["park-migration"]["3600"] < js["park"]["3600"]
    assert js["alley-emergency"]["27010"] > js["alley"]["27010"]
    assert js["local-override"]["29400"] == 50
