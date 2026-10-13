"""Spectral engineering model (Section 4).

Parametric LED spectra on the Planckian locus and the three per-lumen metrics
the spec uses:

  G_R    = ∫ S(λ) λ⁻⁴ dλ / ∫ S(λ) V(λ) dλ        physical Rayleigh scatter per lumen
  G_scot = ∫ S(λ) λ⁻⁴ V'(λ) dλ / ∫ S(λ) V(λ) dλ  skyglow as the dark-adapted eye sees it
  mel-DER = (∫ S s_mel / ∫ S V) / (same for D65)  CIE S 026 melanopic daylight ratio

plus the Mie (aerosol) λ⁻¹·³ factor that dominates near the city and is almost
colour-blind, which is why dimming leads the spec.

Model notes: CIE 1931 colour-matching functions from the Wyman-Sloan-Shirley
(2013) multi-lobe fit; V'(λ) from the CIE 1951 scotopic table at 10 nm;
s_mel(λ) as a Govardovskii A1 nomogram at 480 nm behind a 32-year-old lens
(peaks at 484 nm); D65 at 10 nm.

The white spectra are a 450 nm pump plus two broad phosphor bands fitted to
the Planckian locus, so they are generic, not any vendor's engine. Ratios
between neighbouring CCTs are good to a few percent; the 2200K model is
leaner in cyan than many commercial 2200K engines, which makes its skyglow
and melanopic figures lower than the Section 4 text quotes. For procurement
numbers, load the LM-79 spectra with `load_spd_csv` instead.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Tuple

LAMBDA = list(range(380, 781))   # 1 nm grid


# ----------------------------------------------------------------- functions
def _g(lam: float, mu: float, s1: float, s2: float) -> float:
    s = s1 if lam < mu else s2
    return math.exp(-0.5 * ((lam - mu) / s) ** 2)


def cmf_x(l: float) -> float:
    return 1.056 * _g(l, 599.8, 37.9, 31.0) + 0.362 * _g(l, 442.0, 16.0, 26.7) - 0.065 * _g(l, 501.1, 20.4, 26.2)


def cmf_y(l: float) -> float:
    return 0.821 * _g(l, 568.8, 46.9, 40.5) + 0.286 * _g(l, 530.9, 16.3, 31.1)


def cmf_z(l: float) -> float:
    return 1.217 * _g(l, 437.0, 11.8, 36.0) + 0.681 * _g(l, 459.0, 26.0, 13.8)


_SCOTOPIC_10NM = [  # CIE 1951 V'(λ), 380..780 nm
    0.000589, 0.002209, 0.00929, 0.03484, 0.0966, 0.1998, 0.3281, 0.455, 0.567, 0.676,
    0.793, 0.904, 0.982, 0.997, 0.935, 0.811, 0.650, 0.481, 0.3288, 0.2076,
    0.1212, 0.0655, 0.03315, 0.01593, 0.00737, 0.003335, 0.001497, 0.000677, 0.0003129, 0.0001480,
    0.0000715, 0.00003533, 0.00001780, 0.00000914, 0.00000478, 0.000002546, 0.000001379, 0.00000076,
    0.000000425, 0.000000241, 0.000000139]

_D65_10NM = [  # CIE D65 relative SPD, 380..780 nm
    49.98, 54.65, 82.75, 91.49, 93.43, 86.68, 104.86, 117.01, 117.81, 114.86,
    115.92, 108.81, 109.35, 107.80, 104.79, 107.69, 104.41, 104.05, 100.00, 96.33,
    95.79, 88.69, 90.01, 89.60, 87.70, 83.29, 83.70, 80.03, 80.21, 82.28,
    78.28, 69.72, 71.61, 74.35, 61.60, 69.89, 75.09, 63.59, 46.42, 66.81, 63.38]


def _interp10(table: List[float], lam: float) -> float:
    i = (lam - 380) / 10.0
    k = int(i)
    if k >= len(table) - 1:
        return table[-1]
    f = i - k
    return table[k] * (1 - f) + table[k + 1] * f


def scotopic(lam: float) -> float:
    return _interp10(_SCOTOPIC_10NM, lam)


def d65(lam: float) -> float:
    return _interp10(_D65_10NM, lam)


def _govardovskii_a1(lam: float, lmax: float) -> float:
    x = lmax / lam
    a = 0.8795 + 0.0459 * math.exp(-((lmax - 300.0) ** 2) / 11940.0)
    alpha = 1.0 / (math.exp(69.7 * (a - x)) + math.exp(28.0 * (0.922 - x)) + math.exp(-14.9 * (1.104 - x)) + 0.674)
    lmb = 189.0 + 0.315 * lmax
    bb = -40.5 + 0.195 * lmax
    beta = 0.26 * math.exp(-((lam - lmb) / bb) ** 2)
    return alpha + beta


def _lens_transmittance(lam: float) -> float:
    """Crude 32-year-old lens: strong short-wave absorption."""
    return max(0.0, 1.0 - math.exp(-(lam - 380.0) / 45.0)) if lam > 380 else 0.0


_MEL_RAW = [_govardovskii_a1(l, 480.0) * _lens_transmittance(l) for l in LAMBDA]
_MEL_PEAK = max(_MEL_RAW)
MELANOPIC = [v / _MEL_PEAK for v in _MEL_RAW]
MEL_PEAK_NM = LAMBDA[_MEL_RAW.index(_MEL_PEAK)]

XBAR = [cmf_x(l) for l in LAMBDA]
YBAR = [cmf_y(l) for l in LAMBDA]
ZBAR = [cmf_z(l) for l in LAMBDA]
SCOT = [scotopic(l) for l in LAMBDA]
D65 = [d65(l) for l in LAMBDA]
RAYLEIGH = [(550.0 / l) ** 4 for l in LAMBDA]      # normalised to 550 nm
MIE = [(550.0 / l) ** 1.3 for l in LAMBDA]


# ------------------------------------------------------------------ spectra
def gauss(lam: float, mu: float, fwhm: float) -> float:
    sigma = fwhm / 2.354820045
    return math.exp(-0.5 * ((lam - mu) / sigma) ** 2)


def planck(lam_nm: float, T: float) -> float:
    lam = lam_nm * 1e-9
    c2 = 1.438776877e-2
    return lam ** -5 / (math.exp(c2 / (lam * T)) - 1.0)


def xyz(spd: List[float]) -> Tuple[float, float, float]:
    X = sum(s * x for s, x in zip(spd, XBAR))
    Y = sum(s * y for s, y in zip(spd, YBAR))
    Z = sum(s * z for s, z in zip(spd, ZBAR))
    return X, Y, Z


def xy(spd: List[float]) -> Tuple[float, float]:
    X, Y, Z = xyz(spd)
    s = X + Y + Z
    return (X / s, Y / s) if s > 0 else (0.0, 0.0)


def uv1960(x: float, y: float) -> Tuple[float, float]:
    d = -2 * x + 12 * y + 3
    return 4 * x / d, 6 * y / d


def cct_mccamy(x: float, y: float) -> float:
    n = (x - 0.3320) / (0.1858 - y)
    return 449 * n ** 3 + 3525 * n ** 2 + 6823.3 * n + 5520.33


@lru_cache(maxsize=512)
def _planck_uv(T: float) -> Tuple[float, float]:
    return uv1960(*xy([planck(l, T) for l in LAMBDA]))


def duv(x: float, y: float) -> float:
    """Signed distance from the Planckian locus in CIE 1960 uv; positive above."""
    T = cct_mccamy(x, y)
    T = max(1000.0, min(20000.0, round(T / 5.0) * 5.0))
    u, v = uv1960(x, y)
    up, vp = _planck_uv(T)
    d = math.hypot(u - up, v - vp)
    return d if v > vp else -d


def white_led(pump: float, green: float, red: float, pump_mu: float = 450.0, pump_fwhm: float = 20.0,
              green_mu: float = 550.0, green_fwhm: float = 115.0,
              red_mu: float = 620.0, red_fwhm: float = 80.0) -> List[float]:
    return [pump * gauss(l, pump_mu, pump_fwhm) + green * gauss(l, green_mu, green_fwhm)
            + red * gauss(l, red_mu, red_fwhm) for l in LAMBDA]


def pc_amber(pump_fraction: float = 0.004) -> List[float]:
    """Phosphor-converted amber: broad phosphor at 600 nm (~1850 K) with a residual
    pump ≤ 0.5 % of radiant power."""
    phos = [gauss(l, 600.0, 72.0) for l in LAMBDA]   # ~1850 K, typical PC-Amber
    pump = [gauss(l, 450.0, 20.0) for l in LAMBDA]
    sp, su = sum(phos), sum(pump)
    k = pump_fraction * sp / ((1 - pump_fraction) * su)
    return [p + k * u for p, u in zip(phos, pump)]


def narrow_band_amber() -> List[float]:
    return [gauss(l, 590.0, 16.0) for l in LAMBDA]


@lru_cache(maxsize=32)
def fit_white(cct_target: float) -> Tuple[float, float, float, float]:
    """(pump, green, red, green_mu) that lands on the Planckian locus at the
    target CCT with Duv ≈ 0. Coarse grid then three refinements."""
    best = None
    for green_mu in (540.0, 550.0, 560.0, 570.0):
        lo_p, hi_p, lo_r, hi_r = 0.01, 2.5, 0.0, 4.0
        for _round in range(4):
            n = 16
            for i in range(n + 1):
                p = lo_p + (hi_p - lo_p) * i / n
                for j in range(n + 1):
                    r = lo_r + (hi_r - lo_r) * j / n
                    spd = white_led(p, 1.0, r, green_mu=green_mu)
                    x, y = xy(spd)
                    cct = cct_mccamy(x, y)
                    if not (1500 < cct < 12000):
                        continue
                    cost = (100.0 * math.log(cct / cct_target)) ** 2 + (1000.0 * duv(x, y)) ** 2
                    if best is None or cost < best[0]:
                        best = (cost, p, 1.0, r, green_mu)
            _, bp, _, br, _ = best
            sp, sr = (hi_p - lo_p) / 4, (hi_r - lo_r) / 4
            lo_p, hi_p = max(0.001, bp - sp), bp + sp
            lo_r, hi_r = max(0.0, br - sr), br + sr
    return best[1], best[2], best[3], best[4]


# ------------------------------------------------------------------ metrics
@dataclass
class SpectrumMetrics:
    name: str
    cct: float
    duv: float
    rayleigh_per_lm: float
    scotopic_rayleigh_per_lm: float
    mie_per_lm: float
    mel_der: float
    blue_fraction: float        # radiant power below 500 nm
    ler_lm_per_w: float         # luminous efficacy of radiation

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _der_reference() -> float:
    mel = sum(s * m for s, m in zip(D65, MELANOPIC))
    lum = sum(s * v for s, v in zip(D65, YBAR))
    return mel / lum


_DER_REF = _der_reference()


def metrics(name: str, spd: List[float]) -> SpectrumMetrics:
    lum = sum(s * v for s, v in zip(spd, YBAR))
    rad = sum(spd)
    x, y = xy(spd)
    ray = sum(s * r for s, r in zip(spd, RAYLEIGH)) / lum
    scot = sum(s * r * v for s, r, v in zip(spd, RAYLEIGH, SCOT)) / lum
    mie = sum(s * m for s, m in zip(spd, MIE)) / lum
    mel = sum(s * m for s, m in zip(spd, MELANOPIC)) / lum / _DER_REF
    blue = sum(s for s, l in zip(spd, LAMBDA) if l < 500) / rad
    return SpectrumMetrics(name, cct_mccamy(x, y), duv(x, y), ray, scot, mie, mel, blue, 683.0 * lum / rad)


def spectrum(name: str) -> List[float]:
    if name.endswith("K"):
        p, g, r, gmu = fit_white(float(name[:-1]))
        return white_led(p, g, r, green_mu=gmu)
    if name == "PC-Amber":
        return pc_amber()
    if name in ("NBA", "Narrow-band amber"):
        return narrow_band_amber()
    raise KeyError(name)


def load_spd_csv(path: str) -> List[float]:
    """Read a measured spectrum (two columns: wavelength nm, power in any
    unit; header optional; comma, tab or whitespace separated) and resample
    it linearly onto the 1 nm grid. Outside the measured range is zero."""
    pts: List[Tuple[float, float]] = []
    with open(path, newline="") as f:
        for line in f:
            parts = line.replace(",", " ").replace("\t", " ").replace(";", " ").split()
            if len(parts) < 2:
                continue
            try:
                pts.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue                       # header or comment line
    if len(pts) < 2:
        raise ValueError(f"{path}: need at least two numeric rows")
    pts.sort()
    out: List[float] = []
    j = 0
    for lam in LAMBDA:
        if lam < pts[0][0] or lam > pts[-1][0]:
            out.append(0.0)
            continue
        while j < len(pts) - 2 and pts[j + 1][0] < lam:
            j += 1
        (l0, v0), (l1, v1) = pts[j], pts[j + 1]
        f = 0.0 if l1 == l0 else (lam - l0) / (l1 - l0)
        out.append(max(0.0, v0 + (v1 - v0) * f))
    return out


SPECTRA = ["4000K", "3000K", "2700K", "2200K", "PC-Amber", "Narrow-band amber"]

# Efficacy relative to 3000K assumed by the spec (Section 6.4) for the energy
# model; the LER the model computes is reported alongside but conversion
# losses, not LER, dominate the real penalty.
EFFICACY_REL = {"3000K": 1.00, "2700K": 0.97, "2200K": 0.88, "PC-Amber": 0.70, "4000K": 1.03,
                "Narrow-band amber": 0.55}


@lru_cache(maxsize=1)
def table() -> Dict[str, SpectrumMetrics]:
    return {n: metrics(n, spectrum(n)) for n in SPECTRA}


def relative_table(reference: str = "4000K") -> List[dict]:
    t = table()
    ref = t[reference]
    rows = []
    for n, m in t.items():
        rows.append({
            "spectrum": n,
            "cct_K": round(m.cct),
            "duv": round(m.duv, 4),
            "rayleigh_rel": round(m.rayleigh_per_lm / ref.rayleigh_per_lm, 3),
            "skyglow_scotopic_rel": round(m.scotopic_rayleigh_per_lm / ref.scotopic_rayleigh_per_lm, 3),
            "mie_rel": round(m.mie_per_lm / ref.mie_per_lm, 3),
            "mel_der": round(m.mel_der, 3),
            "blue_fraction": round(m.blue_fraction, 3),
            "ler_lm_per_W": round(m.ler_lm_per_w, 1),
            "efficacy_rel_3000K": EFFICACY_REL.get(n),
        })
    return rows


def rayleigh_rel(name: str, reference: str = "4000K") -> float:
    t = table()
    return t[name].rayleigh_per_lm / t[reference].rayleigh_per_lm


def window_melanopic_edi(ev_lux: float, name: str) -> float:
    """Melanopic EDI (lx) at a window from vertical illuminance under a spectrum."""
    return ev_lux * table()[name].mel_der


if __name__ == "__main__":
    import json
    print(json.dumps(relative_table(), indent=2))
    print("melanopic template peak:", MEL_PEAK_NM, "nm")
