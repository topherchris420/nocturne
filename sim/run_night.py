"""Network night simulation behind Section 6.3 of the spec.

Four sample streets per road class (20 streets, 400 VDL-7 nodes), each a
20-pole Wi-SUN chain at 30 m spacing, driven through the night of
13-14 October 2026 by a modelled CMS: 15-minute hellos with time, ATSPM loop
volumes per segment for arterials and collectors, signed weather events, CAD
incidents turned into a 400 m geofence node list, and Poisson pedestrians who
walk 4-14 poles and trip each node's radar as they pass. Results are scaled
to DC's 75,000 lights by the class mix in Section 6.4.

    python -m sim.run_night --out out            # all scenarios, charts, JSON
    python -m sim.run_night --scenario outage    # one scenario

Assumptions are those tabulated in Section 6.4 and marked ASSUMED there.
Pedestrians and traffic noise come from per-street seeded generators, so
every scenario sees the same people at the same times.
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
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from vdl7 import spectral
from vdl7.bench import sky_lux
from vdl7.clock import DC_LAT, DC_LON, RtcHoldover, local_hour, parse_local, solar_elevation_deg, to_local
from vdl7.cms import GEOFENCE_RADIUS_M, Cms, geofence
from vdl7.controller import Flash, NodeConfig, VDL7Controller
from vdl7.driver import LuminaireDriver
from vdl7.events import EventKind
from vdl7.mesh import MeshNetwork
from vdl7.profiles import RoadClass, default_bundle

# ----------------------------------------------------------------- settings
CLASS_MIX = {RoadClass.ARTERIAL: 0.18, RoadClass.COLLECTOR: 0.17, RoadClass.LOCAL: 0.45,
             RoadClass.ALLEY: 0.15, RoadClass.PARK: 0.05}
N_LIGHTS = 75_000
STREETS_PER_CLASS = 4
POLES = 20
POLE_SPACING_M = 30.0
WALK_SPEED_MPS = 1.4
UPLIGHT_TODAY = 0.03          # direct uplight, network average (globes, tilt)
UPLIGHT_U0 = 0.0
REFLECTED = 0.12              # ground and facade reflectance
CMS_PERIOD_S = 900
BURN_HOURS = 20_000.0
NIGHT_START = "2026-10-13 18:00"
NIGHT_END = "2026-10-14 08:00"
CLASS_ORDER = [RoadClass.ARTERIAL, RoadClass.COLLECTOR, RoadClass.LOCAL, RoadClass.ALLEY, RoadClass.PARK]
CLASS_LABEL = {RoadClass.ARTERIAL: "Arterial", RoadClass.COLLECTOR: "Collector", RoadClass.LOCAL: "Local residential",
               RoadClass.ALLEY: "Alley", RoadClass.PARK: "Park / river edge"}

# Section 6.3 as printed in VD-DSL-SPEC-001 RevA: (energy, delivered light) vs today
SPEC_TABLE_6_3 = {"today": (1.00, 1.00), "dimming": (0.65, 0.65), "dimming_u0": (0.65, 0.65),
                  "nocturne": (0.70, 0.65), "outage": (0.68, 0.63), "legacy_outage": (1.00, 0.92)}


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
    legacy: bool = False            # cloud-dependent node: fails bright 15 min after losing the CMS
    emergency: Optional[Tuple[str, int, str, int]] = None   # (class, street, start HH:MM, minutes); centred on pole 10
    rain: Optional[Tuple[str, str]] = None
    seed: int = 7


SCENARIOS: Dict[str, Scenario] = {
    "today": Scenario("today", "Today: static 100 %, current CCT", dimming=False, u0=False, warm=False),
    "dimming": Scenario("dimming", "Adaptive dimming only", u0=False, warm=False),
    "dimming_u0": Scenario("dimming_u0", "+ U0 optics", warm=False),
    "nocturne": Scenario("nocturne", "+ warm spectrum (full Nocturne)"),
    "outage": Scenario("outage", "Full Nocturne during a 7-hour carrier outage", outage=("22:30", "05:30")),
    "legacy_outage": Scenario("legacy_outage", "Same hardware, cloud-dependent control, same outage",
                              outage=("22:30", "05:30"), legacy=True),
    "emergency": Scenario("emergency", "Full Nocturne with a CAD incident on one local street 00:40-01:40",
                          emergency=("local", 0, "00:40", 60)),
    "rain": Scenario("rain", "Full Nocturne with rain 23:00-02:00", rain=("23:00", "02:00")),
}


# ------------------------------------------------------------------- model
class Walker:
    __slots__ = ("pole", "direction", "remaining", "t_next")

    def __init__(self, pole: int, direction: int, remaining: int, t_next: float):
        self.pole, self.direction, self.remaining, self.t_next = pole, direction, remaining, t_next


class Street:
    def __init__(self, road: RoadClass, k: int, sim: "NetworkSim"):
        self.road, self.k = road, k
        self.segment = f"{road.value}-{k}"
        self.prof = sim.bundle.profiles[road]
        self.ids = [f"{self.segment}-{i:02d}" for i in range(POLES)]
        self.positions = {nid: (POLE_SPACING_M * i, 0.0) for i, nid in enumerate(self.ids)}
        self.mesh = MeshNetwork()
        self.mesh.chain(self.ids)
        self.nodes: List[VDL7Controller] = []
        for i, nid in enumerate(self.ids):
            cfg = NodeConfig(node_id=nid, road=road, segment_id=self.segment, burn_hours=BURN_HOURS,
                             tunable_white=(sim.scn.warm and road in (RoadClass.COLLECTOR, RoadClass.LOCAL) and i % 4 == 0))
            flash = Flash()
            assert flash.install(sim.bundle_msg, sim.cms.verifier)
            driver = LuminaireDriver.commissioned_for(self.prof, cfg.hin)
            self.nodes.append(VDL7Controller(cfg, flash, RtcHoldover(), sim.cms.verifier, driver))
        self.last_hello = [-math.inf] * POLES
        self.walkers: List[Walker] = []
        self.index = {nid: i for i, nid in enumerate(self.ids)}
        self.ped_rng = random.Random(f"{sim.scn.seed}-ped-{self.segment}")
        self.vol_rng = random.Random(f"{sim.scn.seed}-vol-{self.segment}")


class NetworkSim:
    def __init__(self, scn: Scenario, dt: float = 10.0, start: str = NIGHT_START, end: str = NIGHT_END):
        self.scn = scn
        self.dt = dt
        self.cms = Cms()
        self.bundle = default_bundle(1)
        self.bundle_msg = self.cms.bundle(self.bundle)
        self.utc0 = parse_local(start)
        self.utc_end = parse_local(end)
        self.mono = 0.0
        self.streets = [Street(r, k, self) for r in CLASS_ORDER for k in range(STREETS_PER_CLASS)]
        self._outage = self._window(scn.outage)
        self._rain = self._window(scn.rain)
        self._emergency_at = self._window((scn.emergency[2], scn.emergency[2]))[0] if scn.emergency else None
        self._emergency_sent = False
        self._rain_sent_mono = -math.inf
        self.rejected = 0
        # outputs
        self.series: Dict[RoadClass, List[Tuple[float, float]]] = {r: [] for r in CLASS_ORDER}
        self.mode_counts: Dict[RoadClass, Dict[str, int]] = {r: {} for r in CLASS_ORDER}
        self._acc = {r: [0.0, 0] for r in CLASS_ORDER}
        self._bucket_start = 0.0
        self.energy_kwh = 0.0                 # scaled to 75,000 lights
        self.lumen_h = 0.0                    # delivered light, design-lumen-hours (relative)
        self.skyglow = 0.0                    # upward flux x Rayleigh, relative
        self.base_lumen_h = 0.0               # same lights at 100 %, for ratios

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

    def _deliver(self, st: Street, idx: List[int], msg, backhaul_up: bool) -> None:
        """Backhaul to every addressed node that has it; when the carrier is
        down, the mesh carries it from any node that still does."""
        for i in idx:
            ok = st.nodes[i].receive(msg, self.mono, via="backhaul" if backhaul_up else "mesh")
            self.rejected += 0 if ok else 1

    # --------------------------------------------------------------- CMS
    def _cms_step(self, utc: datetime):
        backhaul_up = not self._in(self._outage, utc)
        h = local_hour(utc)
        if backhaul_up and int(self.mono) % CMS_PERIOD_S == 0:
            for st in self.streets:
                msg = None
                if st.prof.design_volume:
                    vol = traffic_veh15(h, st.road) * st.vol_rng.uniform(0.9, 1.1)
                    msg = self.cms.loop_volume(st.segment, vol, issued=utc)    # one message per segment
                for i, n in enumerate(st.nodes):
                    n.backhaul_hello(self.mono, utc)
                    st.last_hello[i] = self.mono
                    if msg is not None:
                        n.receive(msg, self.mono)
        if self._in(self._rain, utc) and backhaul_up and self.mono - self._rain_sent_mono >= CMS_PERIOD_S:
            msg = self.cms.weather(EventKind.RAIN, ttl_s=1800, issued=utc)    # refreshed while wet
            for st in self.streets:
                for n in st.nodes:
                    n.receive(msg, self.mono)
            self._rain_sent_mono = self.mono
        if self._emergency_at is not None and not self._emergency_sent and utc >= self._emergency_at:
            road, k, _, minutes = self.scn.emergency
            st = next(s for s in self.streets if s.road == RoadClass(road) and s.k == k)
            fence = geofence(st.positions, st.positions[st.ids[POLES // 2]], GEOFENCE_RADIUS_M)
            msg = self.cms.emergency(fence, ttl_s=minutes * 60, incident="F26-1183", issued=utc)
            self._deliver(st, [st.index[n] for n in fence], msg, backhaul_up)
            self._emergency_sent = True

    # ------------------------------------------------------------- walkers
    def _walkers(self, st: Street, h: float):
        rng = st.ped_rng
        if rng.random() < ped_rate_per_h(h) / 3600.0 * self.dt:
            start = 0 if rng.random() < 0.5 else POLES - 1
            st.walkers.append(Walker(start, 1 if start == 0 else -1, rng.randint(4, 14), self.mono))
        step_s = POLE_SPACING_M / WALK_SPEED_MPS
        alive = []
        for w in st.walkers:
            if self.mono >= w.t_next:
                if self.scn.dimming:
                    st.nodes[w.pole].radar_detect(self.mono)
                    for nid, _hops in st.mesh.carpet_targets(st.ids[w.pole]):
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
        elev = solar_elevation_deg(DC_LAT, DC_LON, utc)
        lx = sky_lux(elev)
        lit_today = elev < -3.0
        self._cms_step(utc)
        for st in self.streets:
            self._walkers(st, h)
            road, prof, acc, counts = st.road, st.prof, self._acc[st.road], self.mode_counts[st.road]
            if self.scn.dimming:
                gateways = [st.ids[i] for i in range(POLES) if self.mono - st.last_hello[i] <= 900.0]
                reachable = st.mesh.reachable_from(gateways) if gateways else set()
            for i, n in enumerate(st.nodes):
                if self.scn.dimming:
                    if st.ids[i] in reachable:
                        n.mesh_gateway_seen(self.mono)
                    n.photocell_sample(lx, self.mono)
                    out = n.tick(self.mono, self.dt)
                    # Delivered light is the slewed level; CLO drive only holds
                    # that level flat as the LEDs age, as today's fixtures do.
                    f = out.level / out.drive if out.drive > 0 else 0.0
                    white, amber = (out.white * f, out.amber * f) if n.driver.relay_closed else (0.0, 0.0)
                    mode = out.mode.value
                    if self.scn.legacy and self.mono - st.last_hello[i] > 900.0:
                        white, amber = (100.0, 0.0) if lit_today else (0.0, 0.0)   # fails bright
                        mode = "LOST_COMMS_100%"
                else:
                    white, amber = (100.0, 0.0) if lit_today else (0.0, 0.0)
                    mode = "STATIC"
                self._account(road, prof, white, amber, lit_today, n.cfg.tunable_white)
                acc[0] += white + amber
                acc[1] += 1
                counts[mode] = counts.get(mode, 0) + 1
        self.mono += self.dt
        if self.mono - self._bucket_start >= CMS_PERIOD_S:
            for road in CLASS_ORDER:
                a = self._acc[road]
                self.series[road].append((self.mono, a[0] / max(1, a[1])))
                self._acc[road] = [0.0, 0]
            self._bucket_start = self.mono

    def _account(self, road, prof, white, amber, lit_today, tunable=False):
        n_lights = N_LIGHTS * CLASS_MIX[road] / (POLES * STREETS_PER_CLASS)   # lights this pole stands for
        hours = self.dt / 3600.0
        if self.scn.warm:
            white_cct = "2700K" if (tunable or prof.cct_target == "PC-Amber") else prof.cct_target
            if prof.cct_target == "PC-Amber":
                white, amber = 0.0, white + amber               # park edge: single-channel PC-Amber
        else:
            white_cct = f"{prof.cct_today}K"
        eff_w, eff_a = spectral.EFFICACY_REL[white_cct], spectral.EFFICACY_REL["PC-Amber"]
        lumens = (white + amber) / 100.0 * prof.design_watts      # design watts as the lumen proxy
        watts = prof.design_watts * (white / 100.0 / eff_w + amber / 100.0 / eff_a)
        uplight = UPLIGHT_U0 if self.scn.u0 else UPLIGHT_TODAY
        ray = ((white * spectral.rayleigh_rel(white_cct) + amber * spectral.rayleigh_rel("PC-Amber")) / (white + amber)
               if (white + amber) > 0 else 0.0)
        self.energy_kwh += watts * n_lights * hours / 1000.0
        self.lumen_h += lumens * n_lights * hours
        self.skyglow += lumens * (uplight + REFLECTED) * ray * n_lights * hours
        if lit_today:
            self.base_lumen_h += prof.design_watts * n_lights * hours

    def run(self):
        t0 = time.time()
        steps = int((self.utc_end - self.utc0).total_seconds() / self.dt)
        for _ in range(steps):
            self.step()
        self.elapsed = time.time() - t0
        return self

    # ------------------------------------------------------------ results
    def summary(self) -> dict:
        modes = {}
        for r in CLASS_ORDER:
            c = self.mode_counts[r]
            total = sum(c.values()) or 1
            modes[r.value] = {m: round(v / total, 3) for m, v in sorted(c.items())}
        return {
            "scenario": self.scn.name, "title": self.scn.title,
            "energy_mwh_night": round(self.energy_kwh / 1000.0, 2),
            "delivered_lumen_h_rel": round(self.lumen_h / max(1e-9, self.base_lumen_h), 4),
            "skyglow_rel_raw": self.skyglow,
            "mode_share": modes,
            "rejected_messages": self.rejected,
            "elapsed_s": round(self.elapsed, 1),
            "series": {r.value: [(round(m / 3600.0, 3), round(v, 2)) for m, v in self.series[r]] for r in CLASS_ORDER},
        }


# ------------------------------------------------------------------ report
def _run_one(args) -> dict:
    name, dt = args
    return NetworkSim(SCENARIOS[name], dt=dt).run().summary()


def run_all(names: List[str], dt: float, workers: int = 0) -> Dict[str, dict]:
    workers = workers or min(len(names), os.cpu_count() or 1)
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            outs = list(ex.map(_run_one, [(n, dt) for n in names]))
    else:
        outs = [_run_one((n, dt)) for n in names]
    results = dict(zip(names, outs))
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
    return rows


def write_outputs(results: Dict[str, dict], out_dir: str) -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    written = []
    summary = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "spec": "VD-DSL-SPEC-001 RevA, Section 6.3",
        "night": f"{NIGHT_START} to {NIGHT_END} local",
        "layout": f"{STREETS_PER_CLASS} streets x {POLES} poles per class, {POLE_SPACING_M:.0f} m spacing",
        "lights": N_LIGHTS, "class_mix": {r.value: v for r, v in CLASS_MIX.items()},
        "scenarios": {k: {kk: vv for kk, vv in v.items() if kk != "series"} for k, v in results.items()},
        "spec_table_6_3": {k: {"energy_vs_today": e, "delivered_vs_today": d} for k, (e, d) in SPEC_TABLE_6_3.items()},
        "waterfall": waterfall(results),
        "spectral": spectral.relative_table(),
    }
    if "today" in results and "nocturne" in results:
        saved = results["today"]["energy_mwh_night"] - results["nocturne"]["energy_mwh_night"]
        summary["saved_mwh_per_night"] = round(saved, 2)
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
             f"Night of {summary['night']}; {summary['layout']}; scaled to {summary['lights']:,} lights.", "",
             "| Scenario | Energy vs today | Spec 6.3 | Delivered light vs today | Spec 6.3 | Skyglow index | MWh / night |",
             "|---|---|---|---|---|---|---|"]
    for k, r in s.items():
        se, sd = SPEC_TABLE_6_3.get(k, ("", ""))
        lines.append(f"| {r['title']} | {r.get('energy_vs_today', '')} | {se} | {r.get('delivered_vs_today', '')} | "
                     f"{sd} | {r.get('skyglow_index', '')} | {r['energy_mwh_night']} |")
    lines += ["", "## Skyglow waterfall (upward flux x Rayleigh, today = 1.00)", ""]
    for row in summary["waterfall"]:
        d = "" if row["delta"] is None else f" ({row['delta']:+.3f})"
        lines.append(f"- {row['step']}: {row['index']:.3f}{d}")
    if "annual_savings_gwh" in summary:
        lines += ["", f"Saving vs the static baseline: {summary['saved_mwh_per_night']} MWh per night, about "
                      f"{summary['annual_savings_gwh']} GWh a year (October night x 365)."]
    lines += ["", "## Spectral metrics (per photopic lumen, 4000K = 1.00)", "",
              "| Spectrum | CCT | Duv | Rayleigh | Skyglow (scotopic) | Mie | mel-DER | <500 nm |",
              "|---|---|---|---|---|---|---|---|"]
    for r in summary["spectral"]:
        lines.append(f"| {r['spectrum']} | {r['cct_K']} | {r['duv']:+.4f} | {r['rayleigh_rel']:.2f} | "
                     f"{r['skyglow_scotopic_rel']:.2f} | {r['mie_rel']:.2f} | {r['mel_der']:.2f} | {r['blue_fraction']:.1%} |")
    lines += ["", "## Mode share by class (fraction of node-steps)", ""]
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
    # ordinal blue ramp, validated light-mode steps (darkest = most demanding class)
    colors = {"arterial": "#104281", "collector": "#1c5cab", "local": "#2a78d6", "alley": "#5598e7", "park": "#86b6ef"}
    ink, muted, grid = "#121826", "#4f5b73", "#d3d8e3"

    def hours_axis(ax):
        ax.set_xticks(range(0, 15, 2))
        ax.set_xticklabels([f"{(18 + h) % 24:02d}:00" for h in range(0, 15, 2)], color=muted)
        for x, lab in [(4, "step"), (5, "curfew"), (7, "deep"), (11, "dawn")]:
            ax.axvline(x, color=grid, lw=0.8, ls="--", zorder=0)
            ax.text(x + 0.05, 103, lab, fontsize=8, color=muted)
        ax.set_ylim(0, 110)
        ax.set_xlim(0, 14)
        ax.set_ylabel("mean output, % of design", color=muted)
        ax.tick_params(colors=muted)
        ax.grid(axis="y", color=grid, lw=0.6)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)

    if "nocturne" in results:
        fig, ax = plt.subplots(figsize=(10, 4.5))
        for road, pts in results["nocturne"]["series"].items():
            ax.plot([h for h, _ in pts], [v for _, v in pts], color=colors[road], lw=2,
                    label=CLASS_LABEL[RoadClass(road)])
        hours_axis(ax)
        ax.set_title("Mean output by road class, night of 13-14 Oct 2026 (4 streets x 20 poles per class)",
                     color=ink, fontsize=11)
        ax.legend(loc="lower left", fontsize=8, ncol=3, frameon=False)
        fig.tight_layout()
        p = os.path.join(out_dir, "night_profile.png")
        fig.savefig(p, dpi=150)
        plt.close(fig)
        written.append(p)

    if "outage" in results and "legacy_outage" in results:
        fig, ax = plt.subplots(figsize=(10, 4.2))
        ax.axvspan(4.5, 11.5, color="#eef1f6", label="carrier outage 22:30-05:30", zorder=0)
        for key, lab, col in [("legacy_outage", "cloud-dependent control: fails bright", "#8a94a8"),
                              ("outage", "VDL-7: own clock, own profile (AUTONOMOUS)", "#2a78d6")]:
            pts = results[key]["series"]["local"]
            ax.plot([h for h, _ in pts], [v for _, v in pts], color=col, lw=2, label=lab)
        hours_axis(ax)
        ax.set_title("Local residential streets in a 7-hour carrier outage", color=ink, fontsize=11)
        ax.legend(loc="lower left", fontsize=8, frameon=False)
        fig.tight_layout()
        p = os.path.join(out_dir, "outage_comparison.png")
        fig.savefig(p, dpi=150)
        plt.close(fig)
        written.append(p)

    wf = waterfall(results)
    if len(wf) >= 3:
        fig, ax = plt.subplots(figsize=(8.5, 4.2))
        prev = None
        for x, row in enumerate(wf):
            if row["delta"] is None:
                ax.bar(x, row["index"], color="#8a94a8", width=0.6)
                ax.text(x, row["index"] + 0.02, f"{row['index']:.2f}", ha="center", fontsize=9, color=ink)
            else:
                ax.bar(x, -row["delta"], bottom=row["index"], color="#2a78d6", width=0.6)
                ax.text(x, prev + 0.02, f"{row['delta']:+.3f}", ha="center", fontsize=9, color=ink)
                ax.plot([x - 0.3, x + 0.3], [row["index"]] * 2, color=ink, lw=1)
            prev = row["index"]
        ax.set_xticks(range(len(wf)))
        ax.set_xticklabels([r["step"] for r in wf], fontsize=9, color=muted)
        ax.set_ylim(0, 1.15)
        ax.set_ylabel("upward-flux skyglow index, today = 1.00", color=muted)
        ax.set_title(f"Dimming, optics and spectrum: what each removes (ends at {wf[-1]['index']:.2f})",
                     color=ink, fontsize=11)
        ax.tick_params(colors=muted)
        ax.grid(axis="y", color=grid, lw=0.6)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
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
    ap.add_argument("--workers", type=int, default=0, help="parallel processes (default: one per CPU)")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    if a.list:
        for k, s in SCENARIOS.items():
            print(f"{k:16s} {s.title}")
        return 0
    names = a.scenario or list(SCENARIOS)
    if "today" not in names:
        names = ["today"] + names
    t0 = time.time()
    results = run_all(names, a.dt, a.workers)
    written = write_outputs(results, a.out)
    with open(os.path.join(a.out, "report.md")) as f:
        print(f.read())
    print(f"{len(names)} scenarios in {time.time() - t0:.0f} s; written:", *written, sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
