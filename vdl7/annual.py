"""The business case: a whole year of nights for a whole fleet.

The 400-node simulation shows one October night in detail. A budget needs
every night of the year, the city's real fleet and money. This module walks
a year in 5-minute steps on the node's own astronomical clock and DST rule,
and for each road class integrates what the lights would do under each
strategy:

  today        static full output, dusk to dawn
  phase0       the time-of-night programmes vdl7.schedule exports for the
               networked nodes the city already has: no new hardware.
               Arterials and collectors step hourly at the highest level
               the hour's expected loop volume asks for; streets with no
               presence sensing never go below `unsensed_floor`
  phase1       VDL-7 adaptive control: radar presence, live loop volumes,
               the Section 2.2 floors; expected value of the same walker and
               traffic model the network simulation draws from
  phase1_u0    + the post-top globes retrofitted with top reflectors (U0)
  phase2_warm  + the Section 4 spectrum at the next luminaire replacement
               (arterial 2700K, collector/local/alley 2200K, park PC-Amber)

and reports energy, cost, carbon, delivered light and a skyglow index, plus
how much each phase could cost and still pay for itself (for a whole year;
a run over `days` reports the period's energy only).

Prices, emission factors and the optics' uplight are inputs marked ASSUMED.
DC's fleet comes from DDOT's own asset layer (data/dc/fleet.json).
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Dict, Optional, Tuple

from . import spectral
from .clock import local_hour, solar_elevation_deg, to_local
from .demand import POLE_SPACING_M, POLES, WALK_POLES, WALK_SPEED_MPS, ped_rate_per_h, traffic_veh15
from .profiles import (DEFAULT_PROFILES, PHASE_ORDER, PRESENCE_HOLD_S, CARPET_HOLD_S, CARPET_HOPS, ClassProfile,
                       ProfileBundle, RoadClass, default_bundle, phase_for_hour)
from .schedule import level_at, program
from .sites import DEFAULT_SITE, Site

UTC = timezone.utc
STEP_S = 300.0
NIGHT_ELEVATION = -3.0
SLEW_DOWN_PCT_S = 1.0
REFLECTED = 0.12                     # ground and facade reflectance (as the network simulation)
CLASSES = [RoadClass.ARTERIAL, RoadClass.COLLECTOR, RoadClass.LOCAL, RoadClass.ALLEY, RoadClass.PARK]

# ASSUMED upward light ratio by optic group. Replace with the LM-63 files of
# the installed products: `vdl7.photometry.load_ies(path).ulr`.
ULR_ASSUMED = {"cutoff_roadway": 0.0, "semi_cutoff": 0.02, "teardrop": 0.03, "posttop_globe": 0.08, "other": 0.03}

DATA_DC = os.path.join(os.path.dirname(__file__), "..", "data", "dc", "fleet.json")


@dataclass(frozen=True)
class ClassFleet:
    poles: int
    kw: float                    # full-output kW today (commissioned trim applied)
    cct_today: str               # the class's most common spectrum
    uplight: float               # fleet-average upward light ratio today
    uplight_u0: float = 0.0      # after the U0 retrofit
    cct_mix: Dict[str, float] = field(default_factory=dict)   # spectrum -> share of the class's lights

    def mix(self) -> Dict[str, float]:
        return self.cct_mix or {self.cct_today: 1.0}


@dataclass
class Fleet:
    name: str
    classes: Dict[RoadClass, ClassFleet]
    source: str

    @property
    def poles(self) -> int:
        return sum(c.poles for c in self.classes.values())

    @property
    def kw(self) -> float:
        return sum(c.kw for c in self.classes.values())


def _snap_cct(name: str) -> str:
    """An inventory CCT label onto the nearest spectrum the model carries."""
    if name in spectral.EFFICACY_REL:
        return name
    try:
        k = float(name.strip().rstrip("Kk"))
    except ValueError:
        return "2700K"
    for top, label in ((1900, "PC-Amber"), (2450, "2200K"), (2850, "2700K"), (3500, "3000K")):
        if k < top:
            return label
    return "4000K"


def dc_fleet(path: str = DATA_DC) -> Fleet:
    """DC's active streetlights by class from DDOT's asset layer."""
    with open(path) as f:
        d = json.load(f)
    out = {}
    for c in CLASSES:
        row = d["classes"][c.value]
        cct = {k: v for k, v in row["cct"].items() if k != "unknown"}
        mix: Dict[str, float] = {}
        for k, v in cct.items():
            mix[_snap_cct(k)] = mix.get(_snap_cct(k), 0.0) + v
        n_cct = sum(mix.values())
        mix = {k: round(v / n_cct, 5) for k, v in sorted(mix.items(), key=lambda kv: -kv[1])} if n_cct else {"2700K": 1.0}
        dominant = next(iter(mix))
        optics = row.get("optics", {})
        n = sum(optics.values()) or 1
        ulr = sum(ULR_ASSUMED.get(g, 0.03) * k for g, k in optics.items()) / n
        post = optics.get("posttop_globe", 0)
        ulr_u0 = sum(ULR_ASSUMED.get(g, 0.03) * k for g, k in optics.items() if g != "posttop_globe") / n
        out[c] = ClassFleet(row["poles"], row["trimmed_kw"], dominant, round(ulr, 5), round(ulr_u0 if post else ulr, 5),
                            mix)
    return Fleet("dc", out, f"{d['source']}, retrieved {d['retrieved']}")


def spec_fleet(n_lights: int = 75_000) -> Fleet:
    """The Section 6.4 ASSUMED fleet the 400-node simulation scales to."""
    mix = {RoadClass.ARTERIAL: 0.18, RoadClass.COLLECTOR: 0.17, RoadClass.LOCAL: 0.45,
           RoadClass.ALLEY: 0.15, RoadClass.PARK: 0.05}
    out = {}
    for c, share in mix.items():
        p = DEFAULT_PROFILES[c]
        n = round(n_lights * share)
        out[c] = ClassFleet(n, n * p.design_watts / 1000.0, f"{p.cct_today}K", 0.03, 0.0)
    return Fleet("spec", out, "VD-DSL-SPEC-001 Section 6.4 (ASSUMED)")


@dataclass
class Economics:
    usd_per_kwh: float = 0.13            # ASSUMED delivered energy price
    tco2_per_mwh: float = 0.30           # ASSUMED location-based grid factor
    payback_years_phase0: float = 3.0
    payback_years_phase1: float = 10.0


@lru_cache(maxsize=64)
def _program(prof: ClassProfile, unsensed_floor: float):
    return tuple(program(prof, unsensed_floor))


# ------------------------------------------------------- expected activity
def _walk_boost(step_s: float) -> Tuple[float, float]:
    """For one walker, (sum over poles of boosted seconds, poles boosted),
    averaged over walk lengths: presence 90 s at each pole passed, carpet
    60 s within 3 hops of each detection, as the simulation's walkers do."""
    lo, hi = WALK_POLES
    tot_d = tot_n = 0.0
    for k in range(lo, hi + 1):
        det = [i * step_s for i in range(k)]
        poles = range(0, min(POLES, k + CARPET_HOPS))
        for p in poles:
            spans = []
            if p < k:
                spans.append((det[p], det[p] + PRESENCE_HOLD_S))
            for i in range(max(0, p - CARPET_HOPS), min(k, p + CARPET_HOPS + 1)):
                if i != p:
                    spans.append((det[i], det[i] + CARPET_HOLD_S))
            spans.sort()
            d, cur_s, cur_e = 0.0, None, None
            for s, e in spans:
                if cur_e is None or s > cur_e:
                    if cur_e is not None:
                        d += cur_e - cur_s
                    cur_s, cur_e = s, e
                else:
                    cur_e = max(cur_e, e)
            if cur_e is not None:
                d += cur_e - cur_s
            tot_d += d
            tot_n += 1
    n = hi - lo + 1
    return tot_d / n, tot_n / n


def expected_level(prof: ClassProfile, base: float, h: float, strategy: str, unsensed_floor: float,
                   walk: Tuple[float, float]) -> float:
    """Mean level (% of design) of one pole of this class at local hour h."""
    cap = float(prof.boost_cap)
    a_loop = 0.0
    if prof.design_volume:
        a_loop = min(1.0, traffic_veh15(h, prof.road) / prof.design_volume)
    loop_target = max(base, base + (cap - base) * a_loop)
    if strategy == "static":
        return 100.0
    if strategy == "schedule":                     # exactly the programme vdl7.schedule exports
        return level_at(_program(prof, unsensed_floor), h)
    # adaptive: loop target, raised while a walker's presence or carpet holds the pole
    boosted = cap if prof.occupancy else max(base, base + (cap - base) * max(a_loop, 0.5))
    delta = max(0.0, boosted - loop_target)
    if delta == 0.0:
        return loop_target
    secs, poles = walk
    rate_per_pole_s = ped_rate_per_h(h) / 3600.0 / POLES
    extra = rate_per_pole_s * (secs * delta + poles * delta * delta / (2.0 * SLEW_DOWN_PCT_S))
    return min(boosted, loop_target + extra)


# ------------------------------------------------------------- the year
STRATEGIES = {
    "today": ("static", False, False),
    "phase0": ("schedule", False, False),
    "phase1": ("adaptive", False, False),
    "phase1_u0": ("adaptive", True, False),
    "phase2_warm": ("adaptive", True, True),
}
TITLES = {
    "today": "Today: full output dusk to dawn",
    "phase0": "Phase 0: schedule on the existing networked nodes (no new hardware)",
    "phase1": "Phase 1: VDL-7 adaptive control (radar presence, live loop volumes)",
    "phase1_u0": "Phase 1 + top reflectors in the post-top globes (U0)",
    "phase2_warm": "Phase 2: + warm spectrum at replacement (2200K / PC-Amber)",
}


def _cct_new(prof: ClassProfile) -> str:
    return prof.cct_target if prof.cct_target in spectral.EFFICACY_REL else _snap_cct(prof.cct_target)


def run_year(fleet: Fleet, site: Site = DEFAULT_SITE, year: int = 2027, bundle: Optional[ProfileBundle] = None,
             econ: Optional[Economics] = None, unsensed_floor: float = 50.0, step_s: float = STEP_S,
             walk_step_s: Optional[float] = None, days: Optional[Tuple[str, str]] = None) -> dict:
    """Integrate every strategy over a year (or `days` = (first, last) local
    ISO dates, inclusive) at `site`. Returns a JSON-ready dict. Levels are
    taken at the middle of each 5-minute bucket of local time, which never
    straddles a programme step (they fall on the hour)."""
    bundle = bundle or default_bundle()
    econ = econ or Economics()
    walk = _walk_boost(walk_step_s or POLE_SPACING_M / WALK_SPEED_MPS)
    first = datetime.fromisoformat(days[0]) if days else datetime(year, 1, 1)
    last = datetime.fromisoformat(days[1]) + timedelta(days=1) if days else datetime(year + 1, 1, 1)
    from .clock import local_to_utc
    t = local_to_utc(first, site.tz) + timedelta(seconds=step_s / 2)
    t_end = local_to_utc(last, site.tz)
    hours = step_s / 3600.0
    acc = {s: {c: {"lvl_h": 0.0, "kwh": 0.0, "lm": 0.0, "sky": 0.0} for c in CLASSES} for s in STRATEGIES}
    months = {s: [0.0] * 12 for s in STRATEGIES}
    burn = 0.0
    ray = {name: spectral.rayleigh_rel(name) for name in spectral.EFFICACY_REL}
    eff, sky_w = {}, {}
    for c in CLASSES:
        # today's lights by spectrum; lumens per watt and Rayleigh per lumen of the mix
        mix, prof = fleet.classes[c].mix(), bundle.profiles[c]
        eff_mix = sum(f * spectral.EFFICACY_REL[k] for k, f in mix.items())
        ray_mix = sum(f * spectral.EFFICACY_REL[k] * ray[k] for k, f in mix.items()) / eff_mix
        new = _cct_new(prof)
        eff[c] = {False: 1.0, True: spectral.EFFICACY_REL[new] / eff_mix}
        sky_w[c] = {False: ray_mix, True: ray[new]}
    cache: Dict[Tuple, float] = {}
    while t < t_end:
        if solar_elevation_deg(site.lat, site.lon, t) < NIGHT_ELEVATION:
            burn += hours
            h = local_hour(t, site.tz)
            month = to_local(t, site.tz).month - 1
            bucket = math.floor(h * 12.0)                   # 5-minute bucket of local time
            hq = (bucket + 0.5) / 12.0
            phase = phase_for_hour(hq)
            for c in CLASSES:
                prof, cf = bundle.profiles[c], fleet.classes[c]
                base = float(prof.levels[PHASE_ORDER.index(phase)])
                for s, (mode, u0, warm) in STRATEGIES.items():
                    key = (c, mode, bucket)
                    lvl = cache.get(key)
                    if lvl is None:
                        lvl = cache[key] = expected_level(prof, base, hq, mode, unsensed_floor, walk)
                    kwh = cf.kw * lvl / 100.0 / eff[c][warm] * hours
                    up = cf.uplight_u0 if u0 else cf.uplight
                    lm = cf.kw * lvl / 100.0 * hours                      # design-lumen proxy, today's efficacy
                    a = acc[s][c]
                    a["lvl_h"] += lvl * hours
                    a["kwh"] += kwh
                    a["lm"] += lm
                    a["sky"] += lm * (up + REFLECTED * (1.0 - up)) * sky_w[c][warm]
                    months[s][month] += kwh
        t += timedelta(seconds=step_s)
    return _report(fleet, site, year, days, acc, months, burn, econ, unsensed_floor)


def _report(fleet, site, year, days, acc, months, burn, econ, unsensed_floor) -> dict:
    tot = {s: {k: sum(acc[s][c][k] for c in CLASSES) for k in ("kwh", "lm", "sky")} for s in STRATEGIES}
    base = tot["today"]
    out = {"site": site.name, "lat": site.lat, "lon": site.lon, "tz": site.tz,
           "period": f"{days[0]} to {days[1]}" if days else str(year), "whole_year": not days,
           "fleet": {"name": fleet.name, "source": fleet.source, "poles": fleet.poles, "kw": round(fleet.kw, 1),
                     "classes": {c.value: asdict(v) for c, v in fleet.classes.items()}},
           "burn_hours": round(burn, 1), "economics": asdict(econ), "unsensed_floor_pct": unsensed_floor,
           "strategies": {}}
    for s in STRATEGIES:
        mwh = tot[s]["kwh"] / 1000.0
        row = {"title": TITLES[s], "mwh": round(mwh, 1), "usd": round(mwh * 1000 * econ.usd_per_kwh),
               "tco2": round(mwh * econ.tco2_per_mwh, 1),
               "energy_vs_today": round(tot[s]["kwh"] / base["kwh"], 4) if base["kwh"] else None,
               "light_vs_today": round(tot[s]["lm"] / base["lm"], 4) if base["lm"] else None,
               "skyglow_vs_today": round(tot[s]["sky"] / base["sky"], 4) if base["sky"] else None,
               "mean_level_pct": {c.value: round(acc[s][c]["lvl_h"] / burn, 1) if burn else 0.0 for c in CLASSES},
               "mwh_by_class": {c.value: round(acc[s][c]["kwh"] / 1000.0, 1) for c in CLASSES},
               "mwh_by_month": [round(m / 1000.0, 1) for m in months[s]]}
        row["saved_mwh"] = round(base["kwh"] / 1000.0 - mwh, 1)
        row["saved_usd"] = round(row["saved_mwh"] * 1000 * econ.usd_per_kwh)
        row["saved_tco2"] = round(row["saved_mwh"] * econ.tco2_per_mwh, 1)
        out["strategies"][s] = row
    if days:
        return out                       # payback needs a whole year of savings
    st = out["strategies"]
    usd_class = lambda s, c: acc[s][c]["kwh"] * econ.usd_per_kwh
    gain = {c: usd_class("phase0", c) - usd_class("phase1", c) for c in CLASSES}   # Phase 1 over Phase 0, $/yr
    nodes = fleet.poles
    out["break_even"] = {
        "phase0_integration_usd": round(st["phase0"]["saved_usd"] * econ.payback_years_phase0),
        "phase0_years": econ.payback_years_phase0,
        # every pole gets a node: presence and the carpet run on every class
        # (arterials and collectors also take live loop volumes)
        "phase1_nodes": nodes,
        "phase1_usd_per_node": round(sum(gain.values()) * econ.payback_years_phase1 / nodes, 2) if nodes else None,
        "phase1_usd_per_node_by_class": {
            c.value: round(gain[c] * econ.payback_years_phase1 / fleet.classes[c].poles, 2)
            for c in CLASSES if fleet.classes[c].poles},
        "phase1_years": econ.payback_years_phase1,
    }
    return out


def format_report(r: dict) -> str:
    st = r["strategies"]
    yr = "/yr" if r.get("whole_year", True) else ""
    lines = [f"{r['site']} · {r['period']} · {r['fleet']['poles']:,} lights, {r['fleet']['kw']:,.0f} kW at full output · "
             f"{r['burn_hours']:,.0f} h of night (sun below {NIGHT_ELEVATION:g} deg)",
             f"fleet: {r['fleet']['source']}",
             f"price ${r['economics']['usd_per_kwh']}/kWh, grid {r['economics']['tco2_per_mwh']} tCO2/MWh (ASSUMED)", "",
             f"{'strategy':12s} {'MWh' + yr:>9s} {'energy':>7s} {'light':>6s} {'sky':>6s} {'saved $' + yr:>11s} {'tCO2' + yr:>8s}"]
    for k, s in st.items():
        lines.append(f"{k:12s} {s['mwh']:9,.0f} {s['energy_vs_today']:7.3f} {s['light_vs_today']:6.3f} "
                     f"{s['skyglow_vs_today']:6.3f} {s['saved_usd']:11,.0f} {s['saved_tco2']:8,.0f}")
    be = r.get("break_even")
    if be:
        by = be["phase1_usd_per_node_by_class"]
        lines += ["", f"Phase 0 pays back in {be['phase0_years']:g} years if integration costs under "
                      f"${be['phase0_integration_usd']:,.0f}.",
                  f"Phase 1 nodes on all {be['phase1_nodes']:,} poles pay back on energy alone in {be['phase1_years']:g} "
                  f"years only if each costs under ${be['phase1_usd_per_node']:,.2f} "
                  f"({', '.join(f'{c} ${v:,.2f}' for c, v in by.items())})."]
    else:
        lines += ["", "Payback is reported for a whole year only."]
    for k in ("phase0", "phase1"):
        lines.append(f"mean level {k}: " + ", ".join(f"{c} {v:.0f} %" for c, v in st[k]["mean_level_pct"].items()))
    return "\n".join(lines)
