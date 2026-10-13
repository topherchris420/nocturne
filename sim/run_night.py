"""Network night simulation behind Section 6.3 of the spec.

Five sample streets, one per road class, twenty VDL-7 nodes each on a Wi-SUN
chain, driven through the night of 13-14 October 2026 by a modelled CMS:
15-minute hellos with time, ATSPM loop volumes for arterials and collectors,
weather events, CAD incidents, and Poisson pedestrians who walk 4-14 poles
and trip each node's radar as they pass. Results are scaled to DC's 75,000
lights by the class mix in Section 6.4.

    python -m sim.run_night --out out            # all scenarios, charts, JSON
    python -m sim.run_night --scenario outage    # one scenario, console summary

Assumptions are those tabulated in Section 6.4 and marked ASSUMED there.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from vdl7.bench import sky_lux
from vdl7.clock import DC_LAT, DC_LON, local_hour, parse_local, solar_elevation_deg, to_local, RtcHoldover
from vdl7.controller import Flash, Mode, NodeConfig, VDL7Controller
from vdl7.driver import LuminaireDriver
from vdl7.events import Event, EventKind, Priority
from vdl7.mesh import MeshNetwork
from vdl7.profiles import DEFAULT_PROFILES, RoadClass, default_bundle
from vdl7.security import make_signer
from vdl7 import spectral

# ----------------------------------------------------------------- settings
CLASS_MIX = {RoadClass.ARTERIAL: 0.18, RoadClass.COLLECTOR: 0.17, RoadClass.LOCAL: 0.45,
             RoadClass.ALLEY: 0.15, RoadClass.PARK: 0.05}
N_LIGHTS = 75_000
POLES = 20
POLE_SPACING_M = 30.0
WALK_SPEED_MPS = 1.4
UPLIGHT_TODAY = 0.03          # direct uplight, network average (globes, tilt)
UPLIGHT_U0 = 0.0
REFLECTED = 0.12              # ground and facade reflectance
CMS_PERIOD_S = 900
NIGHT_START = "2026-10-13 18:00"
NIGHT_END = "2026-10-14 08:00"
CLASS_ORDER = [RoadClass.ARTERIAL, RoadClass.COLLECTOR, RoadClass.LOCAL, RoadClass.ALLEY, RoadClass.PARK]
CLASS_LABEL = {RoadClass.ARTERIAL: "Arterial", RoadClass.COLLECTOR: "Collector", RoadClass.LOCAL: "Local residential",
               RoadClass.ALLEY: "Alley", RoadClass.PARK: "Park / river edge"}


def _pw(points: List[Tuple[float, float]], h: float) -> float:
    """Piecewise-linear curve over a 24 h clock given as (hour, value) with
    hours after midnight written as 24+."""
    hh = h if h >= 12 else h + 24
    for (h0, v0), (h1, v1) in zip(points, points[1:]):
        if h0 <= hh <= h1:
            return v0 + (v1 - v0) * (hh - h0) / (h1 - h0)
    return points[-1][1] if hh > points[-1][0] else points[0][1]


TRAFFIC = [(18, 290), (20, 210), (22, 130), (24, 60), (27, 25), (29, 60), (31, 250), (32, 290)]
PEDS = [(18, 30), (21, 15), (23, 6), (25, 2), (27, 1), (29, 2), (31, 15), (32, 20)]


def traffic_veh15(h: float, road: RoadClass) -> float:
    base = _pw(TRAFFIC, h)
    return base if road == RoadClass.ARTERIAL else base * 0.42


def ped_rate_per_h(h: float) -> float:
    return _pw(PEDS, h)


@dataclass
class Scenario:
    name: str
    title: str
    dimming: bool = True            # False: today's static 100 %
    u0: bool = True
    warm: bool = True
    outage: Optional[Tuple[str, str]] = None    # carrier outage, local times
    legacy: bool = False            # cloud-dependent node, fails bright after 15 min
    emergency: Optional[Tuple[str, str, int, int, int]] = None   # (class, start, minutes, pole_from, pole_to)
    rain: Optional[Tuple[str, str]] = None
    mesh_break: Optional[Tuple[str, int]] = None   # (class, pole index): link to pole+1 cut
    seed: int = 7


SCENARIOS: Dict[str, Scenario] = {
    "today": Scenario("today", "Today: static 100 %, current CCT", dimming=False, u0=False, warm=False),
    "dimming": Scenario("dimming", "Adaptive dimming only", u0=False, warm=False),
    "dimming_u0": Scenario("dimming_u0", "+ U0 optics", warm=False),
    "nocturne": Scenario("nocturne", "+ warm spectrum (full Nocturne)"),
    "outage": Scenario("outage", "Full Nocturne during a 7-hour carrier outage", outage=("22:30", "05:30")),
    "legacy_outage": Scenario("legacy_outage", "Cloud-dependent nodes in the same outage",
                              outage=("22:30", "05:30"), legacy=True, warm=False, u0=False),
    "emergency": Scenario("emergency", "Full Nocturne with a CAD incident on the local street 00:40-01:40",
                          emergency=("local", "00:40", 60, 6, 13)),
    "rain": Scenario("rain", "Full Nocturne with rain 23:00-02:00", rain=("23:00", "02:00")),
}


# ------------------------------------------------------------------- model
class Walker:
    __slots__ = ("pole", "direction", "remaining", "t_next")

    def __init__(self, pole: int, direction: int, remaining: int, t_next: float):
        self.pole, self.direction, self.remaining, self.t_next = pole, direction, remaining, t_next


class Street:
    def __init__(self, road: RoadClass, sim: "NetworkSim"):
        self.road = road
        self.prof = sim.bundle.profiles[road]
        self.ids = [f"{road.value}-{i:02d}" for i in range(POLES)]
        self.mesh = MeshNetwork()
        self.mesh.chain(self.ids)
        self.nodes: List[VDL7Controller] = []
        for i, nid in enumerate(self.ids):
            cfg = NodeConfig(node_id=nid, road=road, segment_id=road.value,
                             tunable_white=(sim.scn.warm and road in (RoadClass.COLLECTOR, RoadClass.LOCAL) and i % 4 == 0),
                             burn_hours=20_000.0)
            flash = Flash()
            flash.install(sim.bundle_msg, sim.verifier)
            driver = LuminaireDriver.commissioned_for(self.prof)
            self.nodes.append(VDL7Controller(cfg, flash, RtcHoldover(), sim.verifier, driver))
        self.last_hello = [-math.inf] * POLES
        self.walkers: List[Walker] = []
        self.index = {nid: k for k, nid in enumerate(self.ids)}


class NetworkSim:
    def __init__(self, scn: Scenario, dt: float = 10.0, start: str = NIGHT_START, end: str = NIGHT_END):
        self.scn = scn
        self.dt = dt
        self.rng = random.Random(scn.seed)
        self.signer = make_signer()
        self.verifier = self.signer.public()
        self.bundle = default_bundle(1)
        self.bundle_msg = self.signer.sign_obj(self.bundle.to_dict())
        self.utc0 = parse_local(start)
        self.utc_end = parse_local(end)
        self.mono = 0.0
        self.streets = {r: Street(r, self) for r in CLASS_ORDER}
        self.day = to_local(self.utc0).date()
        self._outage = self._window(scn.outage)
        self._rain = self._window(scn.rain)
        self._emergency_sent = False
        self._mesh_broken = False
        self._rain_sent_mono = -math.inf
        # outputs
        self.series: Dict[RoadClass, List[Tuple[float, float]]] = {r: [] for r in CLASS_ORDER}
        self.mode_series: Dict[RoadClass, List[str]] = {r: [] for r in CLASS_ORDER}
        self._acc = {r: [0.0, 0] for r in CLASS_ORDER}
        self._bucket_start = 0.0
        self.energy_kwh = 0.0                 # scaled to 75,000 lights
        self.lumen_h = 0.0                    # delivered light, design-lumen-hours (relative)
        self.skyglow = 0.0                    # upward flux x Rayleigh, relative
        self.base_lumen_h = 0.0               # same lights at 100 %, for ratios
        self.node_log: List[dict] = []

    def _window(self, w: Optional[Tuple[str, str]]):
        if w is None:
            return None
        d0 = to_local(self.utc0).date()
        a = datetime.combine(d0, datetime.strptime(w[0], "%H:%M").time())
        b = datetime.combine(d0, datetime.strptime(w[1], "%H:%M").time())
        if a < to_local(self.utc0):
            a += timedelta(days=1)
        if b <= a:
            b += timedelta(days=1)
        return parse_local(a.isoformat()), parse_local(b.isoformat())

    def _in(self, w, utc) -> bool:
        return w is not None and w[0] <= utc < w[1]

    # --------------------------------------------------------------- CMS
    def _cms(self, utc: datetime):
        backhaul_up = not self._in(self._outage, utc)
        h = local_hour(utc)
        if backhaul_up and int(self.mono) % CMS_PERIOD_S == 0:
            for st in self.streets.values():
                vol = traffic_veh15(h, st.road) * self.rng.uniform(0.9, 1.1) if st.prof.design_volume else None
                ev = None
                if vol is not None:
                    ev = self.signer.sign_obj(Event(EventKind.LOOP_VOLUME, 900, {"veh15": round(vol, 1)},
                                                    issued=utc.isoformat()).to_dict())
                for k, n in enumerate(st.nodes):
                    n.backhaul_hello(self.mono, utc)
                    st.last_hello[k] = self.mono
                    if ev is not None:
                        n.receive(ev, self.mono)
        # rain: refreshed every 15 min while wet, 30 min TTL
        if self._in(self._rain, utc) and backhaul_up and self.mono - self._rain_sent_mono >= CMS_PERIOD_S:
            ev = self.signer.sign_obj(Event(EventKind.RAIN, 1800, {"mm_h": 2.0}, issued=utc.isoformat(), id="rain").to_dict())
            for st in self.streets.values():
                for n in st.nodes:
                    n.receive(ev, self.mono)
            self._rain_sent_mono = self.mono
        # emergency: one signed event to the geofenced poles, relayed by mesh if needed
        if self.scn.emergency and not self._emergency_sent:
            road, start, minutes, p0, p1 = self.scn.emergency
            w = self._window((start, start))
            if utc >= w[0]:
                st = self.streets[RoadClass(road)]
                ev = self.signer.sign_obj(Event(EventKind.EMERGENCY, minutes * 60, {"cad": "F26-1183"},
                                                issued=utc.isoformat(), id="cad-1183").to_dict())
                for k in range(p0, p1 + 1):
                    st.nodes[k].receive(ev, self.mono, via="backhaul" if backhaul_up else "mesh")
                self._emergency_sent = True
        if self.scn.mesh_break and not self._mesh_broken and utc >= self._window((self.scn.mesh_break[0], self.scn.mesh_break[0]))[0]:
            pass

    # ------------------------------------------------------------- walkers
    def _walkers(self, st: Street, h: float):
        rate = ped_rate_per_h(h) / 3600.0 * self.dt
        if self.rng.random() < rate:
            start = 0 if self.rng.random() < 0.5 else POLES - 1
            direction = 1 if start == 0 else -1
            st.walkers.append(Walker(start, direction, self.rng.randint(4, 14), self.mono))
        step_s = POLE_SPACING_M / WALK_SPEED_MPS
        alive = []
        for w in st.walkers:
            if self.mono >= w.t_next:
                st.nodes[w.pole].radar_detect(self.mono)
                for nid, hops in st.mesh.carpet_targets(st.ids[w.pole]):
                    st.nodes[st.index[nid]].carpet_event(self.mono)
                w.pole += w.direction
                w.remaining -= 1
                w.t_next = self.mono + step_s
            if w.remaining > 0 and 0 <= w.pole < POLES:
                alive.append(w)
        st.walkers = alive

    # ------------------------------------------------------------ one step
    def step(self):
        utc = self.utc0 + timedelta(seconds=self.mono)
        h = local_hour(utc)
        lx = sky_lux(solar_elevation_deg(DC_LAT, DC_LON, utc))
        lit_today = solar_elevation_deg(DC_LAT, DC_LON, utc) < -3.0
        self._cms(utc)
        for road, st in self.streets.items():
            self._walkers(st, h)
            is_gw = lambda nid, st=st: self.mono - st.last_hello[st.index[nid]] <= 900.0
            acc = self._acc[road]
            prof = st.prof
            for k, n in enumerate(st.nodes):
                if self.scn.dimming:
                    if st.mesh.gateway_reachable(st.ids[k], is_gw):
                        n.mesh_gateway_seen(self.mono)
                    n.photocell_sample(lx, self.mono)
                    out = n.tick(self.mono, self.dt)
                    # Delivered light is the slewed level; CLO drive is what the
                    # LEDs are pushed to hold that level flat and is a wash
                    # against today's equally depreciating fixtures.
                    f = out.level / out.drive if out.drive > 0 else 0.0
                    white, amber = (out.white * f, out.amber * f) if n.driver.relay_closed else (0.0, 0.0)
                    mode = out.mode.value
                    if self.scn.legacy and self.mono - st.last_hello[k] > 900.0:
                        white, amber = (100.0, 0.0) if lit_today else (0.0, 0.0)   # fails bright
                        mode = "LOST_COMMS_100%"
                else:
                    white, amber = (100.0, 0.0) if lit_today else (0.0, 0.0)
                    mode = "STATIC"
                self._account(road, prof, white, amber, lit_today, n.cfg.tunable_white)
                acc[0] += white + amber
                acc[1] += 1
            self.mode_series[road].append(mode)
        self.mono += self.dt
        if self.mono - self._bucket_start >= CMS_PERIOD_S:
            for road in CLASS_ORDER:
                a = self._acc[road]
                self.series[road].append((self.mono, a[0] / max(1, a[1])))
                self._acc[road] = [0.0, 0]
            self._bucket_start = self.mono

    def _account(self, road, prof, white, amber, lit_today, tunable=False):
        n_lights = N_LIGHTS * CLASS_MIX[road] / POLES          # lights this pole stands for
        hours = self.dt / 3600.0
        if self.scn.warm:
            white_cct = "2700K" if (tunable or prof.cct_target == "PC-Amber") else prof.cct_target
            amber_cct = "PC-Amber"
            if prof.cct_target == "PC-Amber":
                white, amber = 0.0, white + amber               # park edge: single-channel PC-Amber
        else:
            white_cct, amber_cct = f"{prof.cct_today}K", "PC-Amber"
        eff_w = spectral.EFFICACY_REL[white_cct]
        eff_a = spectral.EFFICACY_REL[amber_cct]
        lumens = (white + amber) / 100.0 * prof.design_watts      # design watts as the lumen proxy
        watts = prof.design_watts * (white / 100.0 / eff_w + amber / 100.0 / eff_a)
        uplight = UPLIGHT_U0 if self.scn.u0 else UPLIGHT_TODAY
        ray = (white * spectral.rayleigh_rel(white_cct) + amber * spectral.rayleigh_rel(amber_cct)) / max(1e-9, white + amber) if (white + amber) > 0 else 0.0
        self.energy_kwh += watts * n_lights * hours / 1000.0
        self.lumen_h += lumens * n_lights * hours
        self.skyglow += lumens * (uplight + REFLECTED) * ray * n_lights * hours
        if lit_today:
            self.base_lumen_h += prof.design_watts * n_lights * hours

    def run(self, progress: bool = False):
        t0 = time.time()
        steps = int((self.utc_end - self.utc0).total_seconds() / self.dt)
        for i in range(steps):
            self.step()
            if progress and i % (steps // 10 or 1) == 0:
                print(f"  {self.scn.name}: {100 * i // steps}%", file=sys.stderr)
        self.elapsed = time.time() - t0
        return self

    # ------------------------------------------------------------ results
    def summary(self) -> dict:
        modes = {}
        for r in CLASS_ORDER:
            ms = self.mode_series[r]
            modes[r.value] = {m: round(ms.count(m) / max(1, len(ms)), 3) for m in sorted(set(ms))}
        return {
            "scenario": self.scn.name, "title": self.scn.title,
            "energy_mwh_night": round(self.energy_kwh / 1000.0, 2),
            "delivered_lumen_h_rel": round(self.lumen_h / max(1e-9, self.base_lumen_h), 4),
            "skyglow_rel_raw": self.skyglow,
            "mode_share": modes,
            "elapsed_s": round(self.elapsed, 1),
            "series": {r.value: [(round(m / 3600.0, 3), round(v, 2)) for m, v in self.series[r]] for r in CLASS_ORDER},
        }


# ------------------------------------------------------------------ report
def run_all(names: List[str], dt: float, progress: bool = False) -> Dict[str, dict]:
    results = {}
    for n in names:
        results[n] = NetworkSim(SCENARIOS[n], dt=dt).run(progress).summary()
    today = results.get("today")
    if today is not None:
        for r in results.values():
            r["energy_vs_today"] = round(r["energy_mwh_night"] / today["energy_mwh_night"], 3)
            r["delivered_vs_today"] = round(r["delivered_lumen_h_rel"] / today["delivered_lumen_h_rel"], 3)
            r["skyglow_index"] = round(r["skyglow_rel_raw"] / today["skyglow_rel_raw"], 3)
    for r in results.values():
        r.pop("skyglow_rel_raw", None)
    return results


def waterfall(results: Dict[str, dict]) -> List[dict]:
    steps = [("Today", "today"), ("Adaptive dimming", "dimming"), ("U0 optics", "dimming_u0"),
             ("Warm spectrum", "nocturne")]
    rows, prev = [], None
    for label, key in steps:
        if key not in results:
            continue
        v = results[key]["skyglow_index"]
        rows.append({"step": label, "index": v, "delta": None if prev is None else round(v - prev, 3)})
        prev = v
    if "nocturne" in results:
        rows.append({"step": "Full Nocturne", "index": results["nocturne"]["skyglow_index"], "delta": None})
    return rows


def write_outputs(results: Dict[str, dict], out_dir: str) -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    written = []
    summary = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "spec": "VD-DSL-SPEC-001 RevA, Section 6.3",
        "night": f"{NIGHT_START} to {NIGHT_END} local",
        "lights": N_LIGHTS, "class_mix": {r.value: v for r, v in CLASS_MIX.items()},
        "scenarios": {k: {kk: vv for kk, vv in v.items() if kk != "series"} for k, v in results.items()},
        "waterfall": waterfall(results),
        "spectral": spectral.relative_table(),
    }
    if "today" in results and "nocturne" in results:
        saved = results["today"]["energy_mwh_night"] - results["nocturne"]["energy_mwh_night"]
        summary["annual_savings_gwh"] = round(saved * 365 / 1000.0, 2)
    p = os.path.join(out_dir, "summary.json")
    with open(p, "w") as f:
        json.dump(summary, f, indent=2)
    written.append(p)
    p = os.path.join(out_dir, "timeseries.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "road_class", "hours_since_1800", "local_time", "mean_output_pct"])
        for name, r in results.items():
            for road, pts in r["series"].items():
                for h, v in pts:
                    lt = to_local(parse_local(NIGHT_START) + timedelta(hours=h))
                    w.writerow([name, road, h, lt.strftime("%H:%M"), v])
    written.append(p)
    written += charts(results, out_dir)
    written.append(write_report(summary, out_dir))
    return written


def write_report(summary: dict, out_dir: str) -> str:
    s = summary["scenarios"]
    lines = ["# Nocturne night simulation: results", "",
             f"Night of {summary['night']}, {summary['lights']:,} lights scaled from 20 poles per class.", "",
             "| Scenario | Energy vs today | Delivered light vs today | Skyglow index | MWh / night |",
             "|---|---|---|---|---|"]
    for k, r in s.items():
        lines.append(f"| {r['title']} | {r.get('energy_vs_today', '')} | {r.get('delivered_vs_today', '')} | "
                     f"{r.get('skyglow_index', '')} | {r['energy_mwh_night']} |")
    lines += ["", "## Skyglow waterfall (upward flux x Rayleigh, today = 1.00)", ""]
    for row in summary["waterfall"]:
        d = "" if row["delta"] is None else f" ({row['delta']:+.3f})"
        lines.append(f"- {row['step']}: {row['index']:.3f}{d}")
    if "annual_savings_gwh" in summary:
        lines += ["", f"Annual energy saving vs the static baseline: about {summary['annual_savings_gwh']} GWh "
                      "(October night x 365)."]
    lines += ["", "## Spectral metrics (per photopic lumen, 4000K = 1.00)", "",
              "| Spectrum | CCT | Duv | Rayleigh | Skyglow (scotopic) | Mie | mel-DER | <500 nm |", "|---|---|---|---|---|---|---|---|"]
    for r in summary["spectral"]:
        lines.append(f"| {r['spectrum']} | {r['cct_K']} | {r['duv']:+.4f} | {r['rayleigh_rel']:.2f} | "
                     f"{r['skyglow_scotopic_rel']:.2f} | {r['mie_rel']:.2f} | {r['mel_der']:.2f} | {r['blue_fraction']:.1%} |")
    lines += ["", "## Mode share by class (fraction of simulation steps)", ""]
    for k, r in s.items():
        lines.append(f"- {k}: " + "; ".join(f"{c} {m}" for c, m in r["mode_share"].items()))
    p = os.path.join(out_dir, "report.md")
    with open(p, "w") as f:
        f.write("\n".join(lines) + "\n")
    return p


def charts(results: Dict[str, dict], out_dir: str) -> List[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return []
    written = []
    colors = {"arterial": "#1f4e9c", "collector": "#2e78c7", "local": "#6aa4de", "alley": "#9ec4ea", "park": "#c7ddf2"}
    def hours_axis(ax):
        ax.set_xticks(range(0, 15, 2))
        ax.set_xticklabels([f"{(18 + h) % 24:02d}:00" for h in range(0, 15, 2)])
        for x, lab in [(4, "step"), (5, "curfew"), (7, "deep"), (11, "dawn")]:
            ax.axvline(x, color="#999", lw=0.8, ls="--")
            ax.text(x + 0.05, 102, lab, fontsize=8, color="#666")
        ax.set_ylim(0, 110)
        ax.set_ylabel("mean output, % of design")
        ax.grid(alpha=0.25)

    if "nocturne" in results:
        fig, ax = plt.subplots(figsize=(10, 4.5))
        for road, pts in results["nocturne"]["series"].items():
            xs = [h for h, _ in pts]
            ys = [v for _, v in pts]
            ax.plot(xs, ys, color=colors[road], lw=2, label=CLASS_LABEL[RoadClass(road)])
        hours_axis(ax)
        ax.set_title("Mean output by road class, simulated night of 13-14 Oct 2026 (VDL-7 controller code)")
        ax.legend(loc="lower left", fontsize=8, ncol=3)
        fig.tight_layout()
        p = os.path.join(out_dir, "night_profile.png")
        fig.savefig(p, dpi=150)
        plt.close(fig)
        written.append(p)

    if "outage" in results and "legacy_outage" in results:
        fig, ax = plt.subplots(figsize=(10, 4.2))
        ax.axvspan(4.5, 11.5, color="#eee", label="carrier outage 22:30-05:30")
        for key, lab, col in [("legacy_outage", "cloud-dependent node: fails bright", "#aaa"),
                              ("outage", "VDL-7 in AUTONOMOUS mode: own clock, own profile", "#1f4e9c")]:
            pts = results[key]["series"]["local"]
            ax.plot([h for h, _ in pts], [v for _, v in pts], color=col, lw=2, label=lab)
        hours_axis(ax)
        ax.set_title("Local residential street in a 7-hour carrier outage")
        ax.legend(loc="lower left", fontsize=8)
        fig.tight_layout()
        p = os.path.join(out_dir, "outage_comparison.png")
        fig.savefig(p, dpi=150)
        plt.close(fig)
        written.append(p)

    wf = waterfall(results)
    if len(wf) >= 3:
        fig, ax = plt.subplots(figsize=(8.5, 4.2))
        x, prev = 0, None
        for row in wf:
            if row["delta"] is None:
                ax.bar(x, row["index"], color="#b8b2a7", width=0.6)
                ax.text(x, row["index"] + 0.02, f"{row['index']:.2f}", ha="center", fontsize=9)
            else:
                ax.bar(x, -row["delta"], bottom=row["index"], color="#5cb85c", width=0.6)
                ax.text(x, prev + 0.02, f"{row['delta']:+.3f}", ha="center", fontsize=9)
            prev = row["index"]
            x += 1
        ax.set_xticks(range(len(wf)))
        ax.set_xticklabels([r["step"] for r in wf], fontsize=9)
        ax.set_ylim(0, 1.15)
        ax.set_ylabel("upward-flux skyglow index, today = 1.00")
        ax.set_title("Dimming, optics and spectrum: what each removes")
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        p = os.path.join(out_dir, "skyglow_waterfall.png")
        fig.savefig(p, dpi=150)
        plt.close(fig)
        written.append(p)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", action="append", help="scenario name(s); default all")
    ap.add_argument("--out", default="out", help="output directory")
    ap.add_argument("--dt", type=float, default=10.0, help="simulation step, seconds")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.list:
        for k, s in SCENARIOS.items():
            print(f"{k:16s} {s.title}")
        return 0
    names = a.scenario or list(SCENARIOS)
    if "today" not in names:
        names = ["today"] + names
    results = run_all(names, a.dt, progress=not a.quiet)
    written = write_outputs(results, a.out)
    print(open(os.path.join(a.out, "report.md")).read())
    print("written:", *written, sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
