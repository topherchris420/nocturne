"""Skyglow where people look up: zenith sky brightness at named places.

The network simulation's skyglow index is one number for the whole city.
People experience the sky at places: the Rock Creek Park planetarium, the
Mall, the Arboretum. This module carries DC's real streetlight grid
(data/dc/grid.csv) to those places through the atmosphere and reports the
streetlights' share of the night sky there, in the units astronomers use
(mag/arcsec^2, as a Sky Quality Meter reads it) and the one everyone
understands: how many stars you can see.

Physics. Single scattering in a plane-parallel atmosphere of molecules
(Rayleigh phase function, 8 km scale height) and aerosol (Henyey-Greenstein
phase function, 1.5 km scale height), with extinction on both legs of the
path, for two emission patterns: light reflected off streets and facades
(Lambertian, upward) and direct uplight from the luminaires (uniform over
the upper hemisphere). This is the near-field core of the Garstang model;
it leaves out Earth curvature and multiple scattering, which matter beyond
roughly 30 km, and terrain and buildings, which block some low paths. The
spectrum enters through `spectral.scatter_weight`.

Calibration. Absolute numbers depend on aerosol load, ground reflectance and
luminaire efficacy, all marked ASSUMED, and the model sees only DDOT's
streetlights, not buildings, signs, sports fields or federal lighting. The
only city-scale measurement of that split, Tucson's 2019 dimming experiment,
put municipal streetlights at about 14 % of the emissions behind its skyglow
(Barentine et al. 2020, JQSRT, doi:10.1016/j.jqsrt.2020.107120) and 13-18 %
of the light satellites see (Kyba et al. 2021, Lighting Res. Technol. 53:189).
`STREETLIGHT_SHARE_PRIOR` uses that until DC has its own SQM network; then
`calibrate()` (or vdl7.observe on a station's logs) replaces it. Reductions
in the streetlight term (`reduction`) are robust to all of this.

The consequence is the reason Nocturne does not stop at the streetlights:
even a perfect streetlight programme moves a sky dominated by other sources
only a little. `sky_scenarios` therefore also models the rest of the city's
lighting following the same curfew through the Night Signal (vdl7.nightsignal).

`plan_retrofits` ranks grid cells by how much fixing their post-top globes
(top reflectors, U0) would darken the sky at the protected places per globe
retrofitted: a capital-programme priority list.
"""
from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple, Union

from . import spectral
from .profiles import RoadClass

NATURAL_MSAS = 22.0                      # natural zenith sky, V band, mag/arcsec^2
STREETLIGHT_SHARE_PRIOR = 0.15           # streetlights' share of artificial zenith light (Tucson, see above)
REFLECTANCE = 0.12                       # share of downward light that leaves upward (ASSUMED)
LM_PER_W = 100.0                         # luminaire efficacy of the installed LEDs (ASSUMED)
ULR_GLOBE = 0.08                         # post-top globe upward light ratio (ASSUMED; see annual.ULR_ASSUMED)
ULR_TEARDROP = 0.03
CELL_RADIUS_M = 314.0                    # radius of a disk with a 0.005 x 0.0064 deg cell's area
CLASSES = [RoadClass.ARTERIAL, RoadClass.COLLECTOR, RoadClass.LOCAL, RoadClass.ALLEY, RoadClass.PARK]
GRID_DC = os.path.join(os.path.dirname(__file__), "..", "data", "dc", "grid.csv")


# --------------------------------------------------------------- units
def cd_from_msas(m: float) -> float:
    """Luminance (cd/m^2) of a sky of m mag/arcsec^2 (V band)."""
    return 10.8e4 * 10 ** (-0.4 * m)


def msas_from_cd(lum: float) -> float:
    return -2.5 * math.log10(lum / 10.8e4)


NATURAL_CD = cd_from_msas(NATURAL_MSAS)


def nelm(msas: float) -> float:
    """Naked-eye limiting magnitude at the zenith from sky brightness
    (Schaefer 1990, in the form Unihedron publishes for the SQM)."""
    return 7.93 - 5.0 * math.log10(10 ** (4.316 - msas / 5.0) + 1.0)


# Stars brighter than magnitude m over the whole sky (Yale Bright Star
# Catalogue cumulative counts, rounded).
_STAR_COUNTS = [(1.0, 15), (2.0, 48), (3.0, 171), (4.0, 513), (5.0, 1602), (6.0, 4800), (6.5, 9100), (7.0, 14000)]


def stars_visible(limit_mag: float) -> int:
    """Stars above the horizon brighter than `limit_mag`: half the
    whole-sky count, log-interpolated."""
    pts = _STAR_COUNTS
    if limit_mag <= pts[0][0]:
        return int(round(pts[0][1] / 2 * 10 ** (0.45 * (limit_mag - pts[0][0]))))
    for (m0, n0), (m1, n1) in zip(pts, pts[1:]):
        if limit_mag <= m1:
            f = (limit_mag - m0) / (m1 - m0)
            return int(round(10 ** (math.log10(n0) + f * (math.log10(n1) - math.log10(n0))) / 2))
    return pts[-1][1] // 2


# ------------------------------------------------------------ atmosphere
@dataclass(frozen=True)
class Atmosphere:
    aod_550: float = 0.15                # aerosol optical depth (ASSUMED; DC's annual mean is near this)
    aerosol_h_m: float = 1500.0
    ssa: float = 0.90                    # aerosol single-scattering albedo
    hg_g: float = 0.70                   # aerosol asymmetry parameter
    rayleigh_tau_550: float = 0.0973
    rayleigh_h_m: float = 8000.0


def _hg(cos_psi: float, g: float) -> float:
    return (1 - g * g) / (4 * math.pi * (1 + g * g - 2 * g * cos_psi) ** 1.5)


def _rayleigh_phase(cos_psi: float) -> float:
    return 3.0 / (16.0 * math.pi) * (1.0 + cos_psi * cos_psi)


_D_GRID = [10 ** (1.0 + 4.3 * i / 119) for i in range(120)]          # 10 m .. 200 km
_Z_GRID = [0.0] + [0.01 * (160000.0 / 0.01) ** (i / 999) for i in range(1000)]  # 0, 1 cm .. 160 km


@lru_cache(maxsize=8)
def _kernels(atm: Atmosphere) -> Dict[Tuple[str, str], List[float]]:
    """Zenith luminance (cd/m^2) at distance d per lumen of upward flux, for
    each (emission, scatterer): emission 'lambert' or 'iso', scatterer 'R'
    (molecules) or 'A' (aerosol), on _D_GRID."""
    er0 = atm.rayleigh_tau_550 / atm.rayleigh_h_m
    ea0 = atm.aod_550 / atm.aerosol_h_m
    sa0 = ea0 * atm.ssa

    def tau_vertical(z):
        return (er0 * atm.rayleigh_h_m * -math.expm1(-z / atm.rayleigh_h_m)
                + ea0 * atm.aerosol_h_m * -math.expm1(-z / atm.aerosol_h_m))

    out = {(e, s): [] for e in ("lambert", "iso") for s in ("R", "A")}
    for d in _D_GRID:
        vals = {k: [] for k in out}
        for z in _Z_GRID:
            r = math.hypot(d, z)
            sin_el = z / r
            cos_psi = -z / r
            tv = tau_vertical(z)
            slant = tv * r / z if z > 0 else (er0 + ea0) * d  # same column, longer path; horizontal at z = 0
            t_total = math.exp(-(slant + tv))
            geo = t_total / (r * r)
            br = er0 * math.exp(-z / atm.rayleigh_h_m) * _rayleigh_phase(cos_psi)
            ba = sa0 * math.exp(-z / atm.aerosol_h_m) * _hg(cos_psi, atm.hg_g)
            lam = sin_el / math.pi                          # Lambertian upward intensity per lumen
            iso = 1.0 / (2.0 * math.pi)                     # uniform upper-hemisphere intensity per lumen
            vals[("lambert", "R")].append(lam * geo * br)
            vals[("lambert", "A")].append(lam * geo * ba)
            vals[("iso", "R")].append(iso * geo * br)
            vals[("iso", "A")].append(iso * geo * ba)
        for k, ys in vals.items():
            out[k].append(sum((ys[i] + ys[i + 1]) * 0.5 * (_Z_GRID[i + 1] - _Z_GRID[i]) for i in range(len(ys) - 1)))
    return out


def kernel(d_m: float, emission: str, scatterer: str, atm: Atmosphere = Atmosphere()) -> float:
    """Zenith luminance (cd/m^2) per lumen emitted upward `d_m` away,
    log-log interpolated, and extrapolated along the end segments outside
    10 m - 200 km. A scatterer that is absent (no aerosol) gives 0."""
    ks = _kernels(atm)[(emission, scatterer)]
    d = max(d_m, 1e-3)
    x = math.log10(d)
    i = max(0, min(len(_D_GRID) - 2, int(math.floor((x - 1.0) / 4.3 * 119))))
    x0, x1 = math.log10(_D_GRID[i]), math.log10(_D_GRID[i + 1])
    f = (x - x0) / (x1 - x0)
    if ks[i] <= 0.0 or ks[i + 1] <= 0.0:
        return max(0.0, ks[i] + min(1.0, max(0.0, f)) * (ks[i + 1] - ks[i]))
    y0, y1 = math.log10(ks[i]), math.log10(ks[i + 1])
    return 10 ** (y0 + f * (y1 - y0))


_DISK_STEP_M = 5.0


@lru_cache(maxsize=8192)
def _disk_mean(d_key: int, radius_m: float, emission: str, scatterer: str, atm: Atmosphere) -> float:
    """Mean kernel over a disk of `radius_m` whose centre is d_key x 5 m
    from the observer: a cell of lights near or around a place. Integrated
    in rings about the observer, where the kernel's 1/s core cancels."""
    d = d_key * _DISK_STEP_M
    lo, hi = max(0.0, d - radius_m), d + radius_m
    n = 400
    tot = 0.0
    for i in range(n):
        r = lo + (hi - lo) * (i + 0.5) / n
        if r <= radius_m - d:
            arc = 2.0 * math.pi
        else:
            c = (r * r + d * d - radius_m * radius_m) / (2.0 * r * d)
            arc = 2.0 * math.acos(max(-1.0, min(1.0, c)))
        tot += kernel(r, emission, scatterer, atm) * r * arc * (hi - lo) / n
    return tot / (math.pi * radius_m ** 2)


_NEAR_RADII = 6.0


@lru_cache(maxsize=64)
def _edge_excess(emission: str, scatterer: str, atm: Atmosphere) -> float:
    edge = _NEAR_RADII * CELL_RADIUS_M
    k = int(round(edge / _DISK_STEP_M))
    return _disk_mean(k, CELL_RADIUS_M, emission, scatterer, atm) / kernel(k * _DISK_STEP_M, emission, scatterer, atm) - 1.0


def _cell_kernel(d: float, emission: str, scatterer: str, atm: Atmosphere) -> float:
    """A cell's kernel at distance d: the mean over the cell's area within
    six cell radii (interpolated between 5 m steps), and beyond that the
    point kernel with the disk's second-order excess, which falls as 1/d^2.
    Continuous everywhere, so a place moving past a cell edge sees no step."""
    edge = _NEAR_RADII * CELL_RADIUS_M
    if d < edge:
        x = d / _DISK_STEP_M
        k = int(math.floor(x))
        f = x - k
        a = _disk_mean(k, CELL_RADIUS_M, emission, scatterer, atm)
        b = _disk_mean(k + 1, CELL_RADIUS_M, emission, scatterer, atm)
        return a + f * (b - a)
    return kernel(d, emission, scatterer, atm) * (1.0 + _edge_excess(emission, scatterer, atm) * (edge / d) ** 2)


# ------------------------------------------------------------------ grid
@dataclass
class Cell:
    lat: float
    lon: float
    kw: Dict[RoadClass, float]           # full-output kW by class
    poles: Dict[RoadClass, int]
    globe_kw: float = 0.0                # post-top globes (the uplight)
    teardrop_kw: float = 0.0

    @property
    def total_kw(self) -> float:
        return sum(self.kw.values())


def load_grid(path: str = GRID_DC) -> List[Cell]:
    cells = []
    with open(path) as f:
        for row in csv.DictReader(f):
            cells.append(Cell(float(row["lat"]), float(row["lon"]),
                              {c: float(row[f"{c.value}_w"]) / 1000.0 for c in CLASSES},
                              {c: int(float(row[f"{c.value}_n"])) for c in CLASSES},
                              float(row.get("posttop_globe_w", 0) or 0) / 1000.0,
                              float(row.get("teardrop_w", 0) or 0) / 1000.0))
    return cells


def distance_m(lat0: float, lon0: float, lat1: float, lon1: float) -> float:
    """Equirectangular distance: exact enough across a city."""
    kx = 111_320.0 * math.cos(math.radians((lat0 + lat1) / 2))
    return math.hypot((lon1 - lon0) * kx, (lat1 - lat0) * 110_574.0)


@dataclass(frozen=True)
class Place:
    key: str
    name: str
    lat: float
    lon: float


# Approximate centroids of places where DC residents go to see the night sky
# or where wildlife needs it. Commissioned SQM stations would replace these.
PLACES_DC = [
    Place("rock-creek", "Rock Creek Park (Nature Center & Planetarium)", 38.9594, -77.0525),
    Place("arboretum", "U.S. National Arboretum", 38.9122, -76.9658),
    Place("kenilworth", "Kenilworth Aquatic Gardens", 38.9124, -76.9420),
    Place("anacostia", "Anacostia Park", 38.8760, -76.9735),
    Place("roosevelt-island", "Theodore Roosevelt Island", 38.8968, -77.0647),
    Place("national-mall", "National Mall (Washington Monument grounds)", 38.8895, -77.0353),
]


@dataclass
class Lighting:
    """What the streetlights are doing at a moment: level (% of full
    output) and spectrum by class (one name, or a mix: name -> share of the
    class's lights), and whether the globes were fixed."""
    level: Dict[RoadClass, float]
    cct: Dict[RoadClass, Union[str, Dict[str, float]]]
    globes_u0: bool = False
    ulr_globe: float = ULR_GLOBE
    ulr_teardrop: float = ULR_TEARDROP


def cell_upward(cell: Cell, light: Lighting, retrofit: bool = False) -> Dict[Tuple[str, str], float]:
    """(emission pattern, spectrum) -> upward lumens from one cell."""
    out: Dict[Tuple[str, str], float] = {}
    total_kw = cell.total_kw
    if total_kw <= 0:
        return out
    lm_class = {c: cell.kw[c] * 1000.0 * LM_PER_W * light.level[c] / 100.0 for c in CLASSES}
    lm_total = sum(lm_class.values())
    mean_frac = lm_total / (total_kw * 1000.0 * LM_PER_W)                 # cell's lumen-weighted level
    globe_ulr = 0.0 if (light.globes_u0 or retrofit) else light.ulr_globe
    up_direct = (cell.globe_kw * globe_ulr + cell.teardrop_kw * light.ulr_teardrop) * 1000.0 * LM_PER_W * mean_frac
    down = lm_total - up_direct
    for c in CLASSES:
        if lm_class[c] <= 0:
            continue
        share = lm_class[c] / lm_total
        spec = light.cct[c]
        for cct, f in ({spec: 1.0} if isinstance(spec, str) else spec).items():
            out[("iso", cct)] = out.get(("iso", cct), 0.0) + up_direct * share * f
            out[("lambert", cct)] = out.get(("lambert", cct), 0.0) + REFLECTANCE * down * share * f
    return out


def streetlight_luminance(cells: Sequence[Cell], place: Place, light: Lighting, atm: Atmosphere = Atmosphere(),
                          eye: str = "photopic", retrofit: Optional[set] = None) -> float:
    """Artificial zenith luminance (cd/m^2) at `place` from the streetlights."""
    total = 0.0
    retrofit = retrofit or set()
    for idx, cell in enumerate(cells):
        d = distance_m(place.lat, place.lon, cell.lat, cell.lon)
        for (emission, cct), lm in cell_upward(cell, light, idx in retrofit).items():
            wr = spectral.scatter_weight(cct, 4.0, eye)
            wa = spectral.scatter_weight(cct, 1.3, eye)
            total += lm * (_cell_kernel(d, emission, "R", atm) * wr + _cell_kernel(d, emission, "A", atm) * wa)
    return total


# ------------------------------------------------------------ the sky
@dataclass
class SkyAt:
    place: str
    streetlight_cd: float
    other_cd: float
    natural_cd: float = NATURAL_CD

    @property
    def total_cd(self) -> float:
        return self.streetlight_cd + self.other_cd + self.natural_cd

    @property
    def msas(self) -> float:
        return msas_from_cd(self.total_cd)

    @property
    def nelm(self) -> float:
        return nelm(self.msas)

    @property
    def stars(self) -> int:
        return stars_visible(self.nelm)

    @property
    def streetlight_share(self) -> float:
        art = self.streetlight_cd + self.other_cd
        return self.streetlight_cd / art if art > 0 else 0.0


def calibrate(model_streetlight_cd: float, measured_msas: float) -> float:
    """Luminance of everything that is not a streetlight or the natural sky,
    from a measured zenith brightness taken while the streetlights ran as
    modelled. Never negative: if the model alone is brighter than the
    measurement, the model's streetlight term is too high and the result is 0."""
    return max(0.0, cd_from_msas(measured_msas) - NATURAL_CD - model_streetlight_cd)


def reduction(today_cd: float, new_cd: float) -> float:
    return 1.0 - new_cd / today_cd if today_cd > 0 else 0.0


# ------------------------------------------------------- retrofit planning
@dataclass
class RetrofitStep:
    cell: int
    lat: float
    lon: float
    globes_kw: float
    gain: Dict[str, float]               # place -> fraction of today's streetlight luminance removed
    score: float


def plan_retrofits(cells: Sequence[Cell], places: Sequence[Place], light: Lighting,
                   weights: Optional[Dict[str, float]] = None, atm: Atmosphere = Atmosphere(),
                   top: int = 20, min_globe_kw: float = 0.5) -> List[RetrofitStep]:
    """Grid cells ranked by weighted reduction of streetlight skyglow at the
    places, per kW of globes fixed (globes are retrofitted per luminaire, and
    kW tracks luminaires within a fleet of similar kits). Cells with fewer
    than `min_globe_kw` of globes (about a dozen) are left to the general
    programme."""
    weights = weights or {p.key: 1.0 for p in places}
    base = {p.key: streetlight_luminance(cells, p, light, atm) for p in places}
    steps = []
    for idx, cell in enumerate(cells):
        if cell.globe_kw <= 0.0 or cell.globe_kw < min_globe_kw or light.globes_u0:
            continue
        gain = {}
        for p in places:
            d = distance_m(p.lat, p.lon, cell.lat, cell.lon)
            delta = 0.0
            for (emission, cct), lm in cell_upward(cell, light).items():
                after = cell_upward(cell, light, retrofit=True).get((emission, cct), 0.0)
                if lm == after:
                    continue
                wr = spectral.scatter_weight(cct, 4.0)
                wa = spectral.scatter_weight(cct, 1.3)
                k = _cell_kernel(d, emission, "R", atm) * wr + _cell_kernel(d, emission, "A", atm) * wa
                delta += (lm - after) * k
            gain[p.key] = delta / base[p.key] if base[p.key] else 0.0
        score = sum(weights.get(k, 0.0) * v for k, v in gain.items()) / cell.globe_kw
        steps.append(RetrofitStep(idx, cell.lat, cell.lon, round(cell.globe_kw, 2), gain, score))
    steps.sort(key=lambda s: -s.score)
    return steps[:top]


# ------------------------------------------------------------ scenarios
MOMENTS = {"evening": 21.0, "after_midnight": 1.5}
SKY_STRATEGIES = ["today", "phase0", "phase1", "phase1_u0", "phase2_warm"]


def lighting_for(strategy: str, hour: float, cct_today: Dict[RoadClass, Union[str, Dict[str, float]]]) -> Lighting:
    """Mean class levels and spectra for a business-case strategy at a local
    hour, from the same expected-value model as vdl7.annual."""
    from .annual import STRATEGIES, _cct_new, _walk_boost, expected_level
    from .demand import POLE_SPACING_M, WALK_SPEED_MPS
    from .profiles import DEFAULT_PROFILES, PHASE_ORDER, phase_for_hour
    mode, u0, warm = STRATEGIES[strategy]
    walk = _walk_boost(POLE_SPACING_M / WALK_SPEED_MPS)
    phase = phase_for_hour(hour)
    level, cct = {}, {}
    for c in CLASSES:
        prof = DEFAULT_PROFILES[c]
        level[c] = expected_level(prof, float(prof.levels[PHASE_ORDER.index(phase)]), hour, mode, 50.0, walk)
        cct[c] = _cct_new(prof) if warm else cct_today[c]
    return Lighting(level, cct, globes_u0=u0)


def sky_scenarios(cells: Sequence[Cell], places: Sequence[Place], cct_today: Dict[RoadClass, Union[str, Dict[str, float]]],
                  share: float = STREETLIGHT_SHARE_PRIOR, other_curfew_cut: float = 0.5,
                  atm: Atmosphere = Atmosphere(), measured: Optional[Dict[str, float]] = None) -> List[dict]:
    """For each place and moment: the streetlights' zenith luminance under
    each strategy, and the whole sky (msas, naked-eye limit, stars) today,
    with Nocturne, and with Nocturne plus the rest of the city's lighting
    cutting `other_curfew_cut` of its output after 23:00 via the Night
    Signal. `measured` (place key -> msas, taken with today's lighting)
    replaces the share prior where a station exists."""
    if not (0.0 < share <= 1.0):
        raise ValueError(f"share {share} must be in (0, 1]: the streetlights' fraction of the artificial light")
    if not (0.0 <= other_curfew_cut <= 1.0):
        raise ValueError(f"other_curfew_cut {other_curfew_cut} must be in [0, 1]")
    rows = []
    for p in places:
        for moment, hour in MOMENTS.items():
            lum = {s: streetlight_luminance(cells, p, lighting_for(s, hour, cct_today), atm) for s in SKY_STRATEGIES}
            today_sl = lum["today"]
            if measured and p.key in measured:
                other = calibrate(today_sl, measured[p.key])
                source = "measured"
            else:
                other = today_sl * (1.0 - share) / share
                source = f"prior: streetlights {share:.0%} of artificial light"
            after_curfew = hour < 12 or hour >= 23
            other_signal = other * (1.0 - other_curfew_cut) if after_curfew else other
            skies = {"today": SkyAt(p.key, today_sl, other),
                     "nocturne": SkyAt(p.key, lum["phase2_warm"], other),
                     "nocturne_plus_signal": SkyAt(p.key, lum["phase2_warm"], other_signal)}
            rows.append({
                "place": p.key, "name": p.name, "moment": moment, "hour": hour, "other_source": source,
                "other_curfew_cut": other_curfew_cut,
                "streetlight_mcd": {s: round(v * 1000, 3) for s, v in lum.items()},
                "streetlight_reduction": {s: round(reduction(today_sl, v), 3) for s, v in lum.items()},
                "sky": {k: {"msas": round(v.msas, 2), "nelm": round(v.nelm, 2), "stars": v.stars,
                            "streetlight_share": round(v.streetlight_share, 3)} for k, v in skies.items()},
            })
    return rows


def format_sky(rows: List[dict]) -> str:
    out = [f"{'':18s} {'':15s} {'streetlight sky removed':>27s}   {'whole sky, mag/arcsec^2':>26s}   {'stars overhead':>24s}",
           f"{'place':18s} {'moment':15s} {'p0':>6s}{'p1':>6s}{'+U0':>6s}{'+warm':>7s}   "
           f"{'today':>8s}{'Nocturne':>9s}{'+Signal':>9s}   {'today':>8s}{'Nocturne':>9s}{'+Signal':>9s}"]
    for r in rows:
        red, sk = r["streetlight_reduction"], r["sky"]
        out.append(f"{r['place']:18s} {r['moment']:15s} "
                   f"{red['phase0']:6.0%}{red['phase1']:6.0%}{red['phase1_u0']:6.0%}{red['phase2_warm']:7.0%}   "
                   f"{sk['today']['msas']:8.2f}{sk['nocturne']['msas']:9.2f}{sk['nocturne_plus_signal']['msas']:9.2f}   "
                   f"{sk['today']['stars']:8d}{sk['nocturne']['stars']:9d}{sk['nocturne_plus_signal']['stars']:9d}")
    if rows:
        measured = sorted({r["place"] for r in rows if r["other_source"] == "measured"})
        prior = next((r["other_source"] for r in rows if r["other_source"] != "measured"), None)
        parts = []
        if measured:
            parts.append("measured at " + ", ".join(measured))
        if prior:
            parts.append(prior + (" elsewhere" if measured else ""))
        out.append(f"other lighting: {'; '.join(parts)}. Signal: the rest of the city's lighting cuts "
                   f"{rows[0]['other_curfew_cut']:.0%} of its output after 23:00. Higher mag/arcsec^2 is darker.")
    return "\n".join(out)
