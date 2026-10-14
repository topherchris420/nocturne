"""Section 3 verification: luminaire photometry, BUG ratings, light trespass.

The spec's U0 requirement is checked on paper: a manufacturer's IES LM-63
photometric file goes in, zonal lumens and the IES TM-15-11 (Addendum A)
Backlight-Uplight-Glare rating come out. The same code answers the question
residents actually ask, "how much of this light reaches my bedroom window,
and does it matter?", as vertical illuminance at the window, its melanopic
equivalent under the luminaire's spectrum, and the CIE 150 limits for light
intrusion into windows before and after curfew.

    phot = load_ies("fixture.ies")
    phot.bug()                       # BugRating(B=1, U=0, G=1, ...)
    window_exposure(phot, mounting_h_m=9, setback_m=10, window_h_m=5)

Conventions (Type C photometry, the roadway norm): vertical angle V from
nadir (0 = straight down, 90 = horizontal, 180 = straight up); horizontal
angle H about the vertical axis with 0 along the road and 90 toward the
street. TM-15 calls the street half (H 0-180) *front* and the house half
(H 180-360) *back*; pass `street_side_h` if a file uses another convention.
Files declaring rotational or quadrant symmetry are rated against the
TM-15 glare table for quadrilateral-symmetric (Type V / VS) luminaires.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# -------------------------------------------------------------- TM-15 zones
ZONES = {                       # name: (V from, V to, half): half is "front", "back" or "all"
    "BL": (0, 30, "back"), "BM": (30, 60, "back"), "BH": (60, 80, "back"), "BVH": (80, 90, "back"),
    "FL": (0, 30, "front"), "FM": (30, 60, "front"), "FH": (60, 80, "front"), "FVH": (80, 90, "front"),
    "UL": (90, 100, "all"), "UH": (100, 180, "all"),
}

# IES TM-15-11 Addendum A, Tables A-1 to A-3: maximum zonal lumens for
# ratings 0..4; anything above the last column is rating 5. (Reproduced in
# California's 2016 Title 24 Tables 130.2-A/B and CALGreen 5.106.8.)
B_TABLE = {"BH": (110, 500, 1000, 2500, 5000), "BM": (220, 1000, 2500, 5000, 8500),
           "BL": (110, 500, 1000, 2500, 5000)}
U_TABLE = {"UH": (0, 10, 50, 500, 1000), "UL": (0, 10, 50, 500, 1000)}
G_TABLE_ASYM = {"FVH": (10, 100, 225, 500, 750), "BVH": (10, 100, 225, 500, 750),
                "FH": (660, 1800, 5000, 7500, 12000), "BH": (110, 500, 1000, 2500, 5000)}
G_TABLE_SYM = {"FVH": (10, 100, 225, 500, 750), "BVH": (10, 100, 225, 500, 750),
               "FH": (660, 1800, 5000, 7500, 12000), "BH": (660, 1800, 5000, 7500, 12000)}

# CIE 150 maximum vertical illuminance on windows (lx), (pre-curfew,
# post-curfew), by environmental zone. Post-curfew E1 is 0 except for public
# road lighting, which may reach 1 lx; streetlights are public road lighting.
CIE150_WINDOW_LX = {"E1": (2.0, 1.0), "E2": (5.0, 1.0), "E3": (10.0, 2.0), "E4": (25.0, 5.0)}

# Brown et al. 2022 (PLOS Biology) recommendation: melanopic EDI at the eye
# no higher than 1 lx in the sleep environment.
SLEEP_MEL_EDI_LX = 1.0


def _rating(value: float, limits: Sequence[float]) -> int:
    for r, lim in enumerate(limits):
        if value <= lim + 1e-9:
            return r
    return len(limits)


@dataclass
class BugRating:
    B: int
    U: int
    G: int
    zones: Dict[str, float]
    limiting: Dict[str, str]                       # which zone set each rating
    symmetric_table: bool

    def __str__(self) -> str:
        return f"B{self.B}-U{self.U}-G{self.G}"


@dataclass
class Photometry:
    """Candela table on Type C angles, already scaled by the file's
    multiplier and ballast factors. `candela[i][j]` is at h_angles[i],
    v_angles[j]."""
    v_angles: List[float]
    h_angles: List[float]
    candela: List[List[float]]
    lumens_rated: Optional[float] = None          # None for absolute (LED) photometry
    input_watts: Optional[float] = None
    keywords: Dict[str, str] = field(default_factory=dict)
    street_side_h: float = 90.0
    tilt_ignored: bool = False
    file_generation_type: Optional[float] = None  # LM-63-2019 only: how the file was made, never a multiplier

    def __post_init__(self):
        self._zcache: Dict[Tuple[float, float, float], Dict[str, float]] = {}
        self.symmetry = _symmetry(self.h_angles)
        self._full_h, self._full_c = _expand(self.h_angles, self.candela, self.symmetry)

    def file_h(self, dx: float, dy: float) -> float:
        """The file's horizontal angle for a direction (dx along the road,
        dy toward the street), honouring `street_side_h`."""
        return (math.degrees(math.atan2(dy, dx)) + self.street_side_h - 90.0) % 360.0

    def _wrap(self, h: float) -> float:
        """h on the expanded table's circle, which starts at its first angle."""
        h %= 360.0
        return h + 360.0 if h < self._full_h[0] else h

    # ------------------------------------------------------------ lookups
    def intensity(self, v: float, h: float) -> float:
        """Candela at (V, H) by bilinear interpolation; zero outside the
        measured vertical range."""
        va = self.v_angles
        if v < va[0] - 1e-9 or v > va[-1] + 1e-9:
            return 0.0
        hs, cs = self._full_h, self._full_c
        if len(hs) == 1:
            return _interp1(va, cs[0], v)
        h = self._wrap(h)
        k = _bracket(hs, h)
        h0, h1 = hs[k], hs[k + 1]
        f = 0.0 if h1 == h0 else (h - h0) / (h1 - h0)
        return (1 - f) * _interp1(va, cs[k], v) + f * _interp1(va, cs[k + 1], v)

    # ------------------------------------------------------------ zonal lumens
    def zonal_lumens(self, dv: float = 0.5, dh: float = 1.0) -> Dict[str, float]:
        """Lumens in each TM-15 zone plus 'total', 'front', 'back', 'up', by
        the midpoint rule on a dv x dh degree grid."""
        key = (dv, dh, self.street_side_h)
        if key in self._zcache:
            return dict(self._zcache[key])
        zones = {z: 0.0 for z in ZONES}
        front = back = up = total = 0.0
        nv, nh = int(round(180 / dv)), int(round(360 / dh))
        dvr, dhr = math.radians(dv), math.radians(dh)
        hs = [(j + 0.5) * dh for j in range(nh)]
        is_front = [((h - self.street_side_h + 90.0) % 360.0) < 180.0 for h in hs]
        full_h, full_c = self._full_h, self._full_c
        if len(full_h) == 1:
            brackets = [(0, 0.0)] * nh
        else:
            brackets = []
            for h in hs:
                hw = self._wrap(h)
                k = _bracket(full_h, hw)
                brackets.append((k, (hw - full_h[k]) / (full_h[k + 1] - full_h[k])))
        for i in range(nv):
            v = (i + 0.5) * dv
            if v < self.v_angles[0] or v > self.v_angles[-1]:
                continue
            col = [_interp1(self.v_angles, row, v) for row in full_c]
            w = math.sin(math.radians(v)) * dvr * dhr
            f = b = 0.0
            for (k, frac), fr in zip(brackets, is_front):
                val = col[k] if len(col) == 1 else col[k] * (1 - frac) + col[k + 1] * frac
                if fr:
                    f += val
                else:
                    b += val
            f, b = f * w, b * w
            total += f + b
            if v >= 90.0:
                up += f + b
                zones["UL" if v < 100.0 else "UH"] += f + b
                continue
            band = "L" if v < 30 else "M" if v < 60 else "H" if v < 80 else "VH"
            zones["F" + band] += f
            zones["B" + band] += b
            front += f
            back += b
        zones.update(total=total, front=front, back=back, up=up)
        self._zcache[key] = dict(zones)
        return zones

    def quadrilateral_symmetric(self, tol: float = 0.05) -> bool:
        """Type V / VS: the distribution repeats every 90 deg of H (within
        `tol` of its peak), whatever range the file happens to declare."""
        if len(self._full_h) == 1:
            return True
        peak = max(max(row) for row in self._full_c) or 1.0
        for v in self.v_angles:
            for h in range(0, 360, 5):
                if abs(self.intensity(v, h) - self.intensity(v, h + 90.0)) > tol * peak:
                    return False
        return True

    def bug(self, type_v: Optional[bool] = None) -> BugRating:
        """TM-15-11 rating. The glare table for quadrilateral-symmetric
        luminaires applies when the light repeats every 90 deg; pass
        `type_v` to state the luminaire's IES type instead."""
        z = self.zonal_lumens()
        sym = self.quadrilateral_symmetric() if type_v is None else bool(type_v)
        out, why = {}, {}
        for name, table in (("B", B_TABLE), ("U", U_TABLE), ("G", G_TABLE_SYM if sym else G_TABLE_ASYM)):
            ratings = {zone: _rating(z[zone], lims) for zone, lims in table.items()}
            zone = max(ratings, key=lambda k: (ratings[k], z[k]))
            out[name], why[name] = ratings[zone], zone
        return BugRating(out["B"], out["U"], out["G"], z, why, sym)

    @property
    def ulr(self) -> float:
        """Upward light ratio: share of luminaire lumens above horizontal."""
        z = self.zonal_lumens()
        return z["up"] / z["total"] if z["total"] > 0 else 0.0

    # ------------------------------------------------------------ illuminance
    def illuminance(self, mounting_h_m: float, point: Tuple[float, float, float],
                    normal: Tuple[float, float, float]) -> float:
        """Illuminance (lx) at `point` (x along the road, y toward the
        street, z up; metres, luminaire at (0, 0, mounting_h_m), aimed at
        nadir) on a surface facing `normal`."""
        dx, dy, dz = point[0], point[1], point[2] - mounting_h_m
        r = math.sqrt(dx * dx + dy * dy + dz * dz)
        if r == 0:
            return 0.0
        v = math.degrees(math.acos(max(-1.0, min(1.0, -dz / r))))
        h = self.file_h(dx, dy)
        nn = math.sqrt(sum(c * c for c in normal))
        cos_inc = -(dx * normal[0] + dy * normal[1] + dz * normal[2]) / (r * nn)
        if cos_inc <= 0:
            return 0.0
        return self.intensity(v, h) * cos_inc / (r * r)


# ------------------------------------------------------------------ helpers
def _bracket(xs: List[float], x: float) -> int:
    lo, hi = 0, len(xs) - 1
    if x <= xs[0]:
        return 0
    if x >= xs[-1]:
        return len(xs) - 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    return lo


def _interp1(xs: List[float], ys: List[float], x: float) -> float:
    if len(xs) == 1:
        return ys[0]
    k = _bracket(xs, x)
    x0, x1 = xs[k], xs[k + 1]
    f = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
    f = max(0.0, min(1.0, f))
    return ys[k] * (1 - f) + ys[k + 1] * f


def _symmetry(h: List[float]) -> str:
    first, last = h[0], h[-1]
    if len(h) == 1:
        return "rotational"
    if first == 0 and last == 90:
        return "quadrant"
    if first == 0 and last == 180:
        return "bilateral-0-180"
    if first == 90 and last == 270:
        return "bilateral-90-270"
    if first == 0 and last == 360:
        return "full"
    if first == 0 and 180 < last < 360:
        return "partial"                      # treated as full; the rest of the circle is 0..last wrap
    raise ValueError(f"unsupported horizontal angle range {first}..{last}")


def _expand(h: List[float], cd: List[List[float]], sym: str) -> Tuple[List[float], List[List[float]]]:
    """The candela table over the full circle 0..360, from the symmetry the
    file declares (LM-63)."""
    if sym == "rotational":
        return [0.0], [list(cd[0])]
    pts: Dict[float, List[float]] = {}
    for a, row in zip(h, cd):
        pts[a % 360.0] = list(row)
        if sym == "quadrant":                 # mirror about 0-180 and 90-270 planes
            for b in (180.0 - a, 180.0 + a, 360.0 - a):
                pts.setdefault(b % 360.0, list(row))
        elif sym == "bilateral-0-180":        # I(H) = I(360 - H)
            pts.setdefault((360.0 - a) % 360.0, list(row))
        elif sym == "bilateral-90-270":       # I(H) = I(180 - H)
            pts.setdefault((180.0 - a) % 360.0, list(row))
    hs = sorted(pts)
    rows = [pts[a] for a in hs]
    hs.append(hs[0] + 360.0)                  # close the circle (a 90-270 file without 180 starts at 30)
    rows.append(list(rows[0]))
    return hs, rows


# ------------------------------------------------------------------ LM-63
def _lm63_year(first_line: str) -> Optional[int]:
    """The LM-63 edition a file's first line names ('IESNA:LM-63-2002',
    'IES:LM-63-2019', 'IESNA91'), or None for the 1986 format, which has no
    such line."""
    s = first_line.lstrip("﻿ï»¿").strip().upper()     # a UTF-8 BOM, read as UTF-8 or latin-1
    m = re.match(r"IES(?:NA)?\s*:\s*LM-63-(\d{4})", s)
    if m:
        return int(m.group(1))
    m = re.match(r"IESNA\s*(\d{2})\b", s)
    return 1900 + int(m.group(1)) if m else None


def parse_ies(text: str, street_side_h: float = 90.0) -> Photometry:
    """Parse an IES LM-63 (1986, 1991, 1995, 2002 or 2019) photometric file.
    Only Type C photometry, the roadway and area-lighting norm, is accepted.
    Anything after the candela table (an end-of-file marker, a note) is
    ignored.

    The second value after the photometric line depends on the edition: the
    ballast-lamp photometric factor up to LM-63-1995 (applied to the
    candela values), 'future use' in LM-63-2002 (ignored), and the file
    generation type in LM-63-2019 (1.10000 means 'accredited laboratory',
    not 10 % more light: recorded in `file_generation_type`, never applied)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    year = _lm63_year(lines[0])
    keywords: Dict[str, str] = {}
    last_key: Optional[str] = None
    i = 0
    while i < len(lines) and not re.match(r"\s*TILT\s*=", lines[i], re.I):
        m = re.match(r"\s*\[([^\]]+)\]\s*(.*)", lines[i])
        if m:
            key, value = m.group(1).strip().upper(), m.group(2).strip()
            if key == "MORE" and last_key is not None:          # continues the previous keyword
                keywords[last_key] = (keywords[last_key] + " " + value).strip()
            else:
                keywords[key] = value
                last_key = key
        i += 1
    if i == len(lines):
        raise ValueError("no TILT= line: not an LM-63 file")
    tilt = lines[i].split("=", 1)[1].strip().upper()
    tokens = [t for t in re.split(r"[\s,]+", " ".join(lines[i + 1:]).strip()) if t]
    pos = 0

    def take(n: int) -> List[float]:
        nonlocal pos
        if pos + n > len(tokens):
            raise ValueError("truncated photometric data")
        try:
            vals = [float(t) for t in tokens[pos:pos + n]]
        except ValueError as e:
            raise ValueError(f"non-numeric value in photometric data: {e}") from None
        pos += n
        return vals

    tilt_ignored = False
    if tilt == "INCLUDE":                     # lamp-to-luminaire geometry, n, angles, factors
        _geometry, n = take(2)
        take(2 * int(n))
        tilt_ignored = True
    elif tilt != "NONE":
        raise ValueError(f"TILT={tilt}: external tilt files are not supported")
    n_lamps, lm_per_lamp, mult, n_v, n_h, ptype, _units, _w, _l, _ht = take(10)
    ballast, bl_factor, watts = take(3)
    n_v, n_h = int(n_v), int(n_h)
    if n_v < 1 or n_h < 1:
        raise ValueError("photometric data needs at least one vertical and one horizontal angle")
    v = take(n_v)
    h = take(n_h)
    raw = take(n_v * n_h)
    if int(ptype) != 1:
        raise ValueError(f"photometric type {int(ptype)}: only Type C (1) is supported")
    if v != sorted(v) or h != sorted(h):
        raise ValueError("angles must be ascending")
    if not (v[0] in (0.0, 90.0) and v[-1] in (90.0, 180.0)):
        raise ValueError(f"vertical angles {v[0]}..{v[-1]} are not a Type C range")
    blpf_edition = year is None or year < 2002                   # a multiplier only up to LM-63-1995
    scale = mult * (ballast if ballast > 0 else 1.0) * (bl_factor if blpf_edition and 0 < bl_factor <= 2 else 1.0)
    cd = [[raw[k * n_v + j] * scale for j in range(n_v)] for k in range(n_h)]
    rated = None if lm_per_lamp < 0 else n_lamps * lm_per_lamp
    return Photometry(v, h, cd, rated, watts if watts > 0 else None, keywords, street_side_h, tilt_ignored,
                      bl_factor if year is not None and year >= 2019 else None)


def load_ies(path: str, street_side_h: float = 90.0) -> Photometry:
    with open(path, encoding="latin-1") as f:
        return parse_ies(f.read(), street_side_h)


def write_ies(phot: Photometry, keywords: Optional[Dict[str, str]] = None, watts: float = 0.0) -> str:
    """LM-63-2002 text for a candela table (absolute photometry)."""
    kw = dict(keywords or phot.keywords)
    out = ["IESNA:LM-63-2002"] + [f"[{k}] {v}" for k, v in kw.items()] + ["TILT=NONE"]
    out.append(f"1 -1 1 {len(phot.v_angles)} {len(phot.h_angles)} 1 2 0 0 0")
    out.append(f"1 1 {watts or (phot.input_watts or 0):g}")

    def wrap(vals):
        row = []
        for k in range(0, len(vals), 10):
            row.append(" ".join(f"{x:g}" for x in vals[k:k + 10]))
        return row
    out += wrap(phot.v_angles) + wrap(phot.h_angles)
    for row in phot.candela:
        out += wrap([round(x, 2) for x in row])
    return "\n".join(out) + "\n"


# ----------------------------------------------------- synthetic luminaires
def synthetic(kind: str, lumens: float = 5000.0, ulr: float = 0.0, watts: float = 0.0) -> Photometry:
    """Smooth analytic distributions for tests and examples. Not products.

    'roadway'  asymmetric street-side throw, no light above 85 deg (U0)
    'globe'    rotationally symmetric post-top with `ulr` of its flux upward
    'isotropic' 1 cd per (lumens / 4 pi) in every direction
    """
    v = [float(x) for x in range(0, 181, 5)]
    if kind == "isotropic":
        i0 = lumens / (4 * math.pi)
        p = Photometry(v, [0.0], [[i0] * len(v)])
        p.input_watts = watts or None
        return p
    if kind == "roadway":
        h = [float(x) for x in range(0, 361, 5)]

        def shape(vv, hh):
            if vv >= 85:
                return 0.0
            taper = 1.0 if vv <= 70 else math.cos(math.radians((vv - 70) / 15 * 90)) ** 2
            lateral = 1.0 + 0.8 * math.sin(math.radians(hh))            # street side brighter
            return (math.cos(math.radians(vv)) ** 0.3 + 1.2 * math.sin(math.radians(vv)) ** 3) * lateral * taper
        table = [[shape(vv, hh) for vv in v] for hh in h]
    elif kind == "globe":
        h = [0.0]

        def down(vv):                         # falls to zero at the horizontal
            if vv >= 90:
                return 0.0
            taper = 1.0 if vv <= 80 else math.cos(math.radians((vv - 80) / 10 * 90)) ** 2
            return (0.6 + 0.4 * math.sin(math.radians(vv))) * taper
        def upv(vv):                          # zero at the horizontal, as `down` is
            return 0.0 if vv <= 90 else math.sin(math.radians(vv)) ** 0.5
        def scaled(k_up):
            return [[down(vv) if vv <= 90 else k_up * upv(vv) for vv in v]]

        def share(k_up):
            z = Photometry(v, h, scaled(k_up)).zonal_lumens(dv=0.5, dh=360.0)
            return z["up"] / z["total"]
        lo_k, hi_k = 0.0, 64.0                # bisect the upper-hemisphere weight to hit `ulr`
        for _ in range(60):
            mid = (lo_k + hi_k) / 2
            lo_k, hi_k = (mid, hi_k) if share(mid) < ulr else (lo_k, mid)
        table = scaled(lo_k if ulr > 0 else 0.0)
    else:
        raise KeyError(kind)
    p = Photometry(v, h, table)
    total = p.zonal_lumens(dv=1.0, dh=5.0)["total"]
    k = lumens / total
    p = Photometry(v, h, [[x * k for x in row] for row in table], input_watts=watts or None)
    return p


# --------------------------------------------------------------- trespass
@dataclass
class WindowExposure:
    ev_lux: float                     # vertical illuminance on the window
    mel_edi_lux: float                # melanopic equivalent daylight illuminance
    v_deg: float
    h_deg: float
    zone: str                         # TM-15 zone the window sits in


def window_exposure(phot: Photometry, mounting_h_m: float, setback_m: float, window_h_m: float,
                    along_m: float = 0.0, level_pct: float = 100.0, spectrum: str = "2700K") -> WindowExposure:
    """Light on a window `setback_m` behind the pole (house side), `along_m`
    up the road, facing the street, with the luminaire at `level_pct`."""
    from . import spectral
    y = -abs(setback_m)
    ev = phot.illuminance(mounting_h_m, (along_m, y, window_h_m), (0.0, 1.0, 0.0)) * level_pct / 100.0
    dx, dy, dz = along_m, y, window_h_m - mounting_h_m
    r = math.sqrt(dx * dx + dy * dy + dz * dz)
    v = math.degrees(math.acos(-dz / r)) if r else 0.0
    h = phot.file_h(dx, dy)
    front = ((h - phot.street_side_h + 90.0) % 360.0) < 180.0
    if v >= 100:
        zone = "UH"
    elif v >= 90:
        zone = "UL"
    else:
        band = "L" if v < 30 else "M" if v < 60 else "H" if v < 80 else "VH"
        zone = ("F" if front else "B") + band
    return WindowExposure(ev, ev * spectral.table()[spectrum].mel_der, v, h, zone)


def trespass_report(phot: Photometry, mounting_h_m: float, setback_m: float, window_h_m: float,
                    levels: Dict[str, float], spectra: Dict[str, str], env_zone: str = "E3") -> List[dict]:
    """One row per phase: vertical illuminance and melanopic EDI at the
    window, against the CIE 150 limit for the environmental zone (the
    post-curfew limit from the curfew phase on) and the 1 lx sleep guide."""
    pre, post = CIE150_WINDOW_LX[env_zone]
    rows = []
    for phase, lv in levels.items():
        w = window_exposure(phot, mounting_h_m, setback_m, window_h_m, level_pct=lv,
                            spectrum=spectra.get(phase, "2700K"))
        limit = post if phase in ("curfew", "deep", "dawn") else pre
        rows.append({"phase": phase, "level_pct": lv, "spectrum": spectra.get(phase, "2700K"),
                     "ev_lux": round(w.ev_lux, 3), "mel_edi_lux": round(w.mel_edi_lux, 3),
                     "cie150_limit_lux": limit, "within_cie150": w.ev_lux <= limit + 1e-9,
                     "below_sleep_guide": w.mel_edi_lux <= SLEEP_MEL_EDI_LX, "zone": w.zone})
    return rows
