"""Whole-sky outcomes at DC's dark places for the technology packages in
docs/TECHNOLOGY.md.

    python tools/sky_packages.py [--share 0.15] [--json]

The streetlights come from vdl7.skyglow on DC's own grid, exactly as
`nocturne sky` computes them. Everything else in the sky is the share
prior's remainder, and two technologies act on it:

* curfew controls (time switches, building automation and sign controllers
  following the Night Signal) cut `curfew` of it after 23:00;
* full shielding removes `shield` of it at every hour. Flagstaff's source
  inventory puts full shielding of all lighting at about half of today's
  sky glow (Luginbuhl et al. 2009, PASP 121:185).

It also reports how much of today's artificial light would have to go for
the Milky Way to show at the zenith: artificial brightness under 688 of the
natural sky's 174 ucd/m^2, about 20.3 mag/arcsec^2 in all (Falchi et al.
2016, Sci. Adv. 2:e1600377, Table 1).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from vdl7.annual import dc_fleet  # noqa: E402
from vdl7.skyglow import (CLASSES, MOMENTS, NATURAL_CD, PLACES_DC, STREETLIGHT_SHARE_PRIOR, Place, SkyAt,  # noqa: E402
                          lighting_for, load_grid, streetlight_luminance)

# Falchi 2016 loses the Milky Way above 688 ucd/m^2 of artificial light on a
# 174 ucd/m^2 natural sky; as a ratio, so it sits on this model's natural sky.
MILKY_WAY_ARTIFICIAL_CD = 688.0 / 174.0 * NATURAL_CD

# name: (streetlight strategy, curfew cut of other lighting after 23:00, shielding cut of it at all hours)
PACKAGES = {
    "today": ("today", 0.0, 0.0),
    "streetlights": ("phase2_warm", 0.0, 0.0),        # Nocturne's full programme: adaptive, U0 globes, warm
    "curfew 30 %": ("today", 0.3, 0.0),               # the Model Lighting Ordinance's minimum reduction
    "curfew 50 %": ("today", 0.5, 0.0),
    "shielding": ("today", 0.0, 0.5),
    "streetlights + curfew 50 %": ("phase2_warm", 0.5, 0.0),
    "all three": ("phase2_warm", 0.5, 0.5),
}


def milky_way_cut(artificial_cd: float) -> float:
    """Share of today's artificial zenith light that must go before the
    Milky Way can be seen there (0 if it already can)."""
    return max(0.0, 1.0 - MILKY_WAY_ARTIFICIAL_CD / artificial_cd) if artificial_cd > 0 else 0.0


def packages(share: float = STREETLIGHT_SHARE_PRIOR, places: Sequence[Place] = PLACES_DC,
             packages: Optional[Dict[str, tuple]] = None) -> List[dict]:
    """One row per place and moment: zenith brightness (mag/arcsec^2) and
    stars overhead under each package, and the cut the Milky Way needs."""
    if not (0.0 < share <= 1.0):
        raise ValueError(f"share {share} must be in (0, 1]: the streetlights' fraction of the artificial light")
    packages = packages or PACKAGES
    for name, (_, curfew, shield) in packages.items():
        if not (0.0 <= curfew <= 1.0 and 0.0 <= shield <= 1.0):
            raise ValueError(f"package {name!r}: curfew and shielding cuts must be in [0, 1]")
    fleet = dc_fleet()
    cct = {c: fleet.classes[c].mix() for c in CLASSES}
    cells = load_grid()
    rows = []
    for p in places:
        for moment, hour in MOMENTS.items():
            lum = {s: streetlight_luminance(cells, p, lighting_for(s, hour, cct))
                   for s in {strategy for strategy, _, _ in packages.values()} | {"today"}}
            other = lum["today"] * (1.0 - share) / share
            after_curfew = hour < 12 or hour >= 23           # as vdl7.skyglow.sky_scenarios
            sky = {}
            for name, (strategy, curfew, shield) in packages.items():
                o = other * (1.0 - shield) * ((1.0 - curfew) if after_curfew else 1.0)
                s = SkyAt(p.key, lum[strategy], o)
                sky[name] = {"msas": round(s.msas, 2), "stars": s.stars}
            rows.append({"place": p.key, "moment": moment, "hour": hour, "share": share, "sky": sky,
                         "milky_way_cut": round(milky_way_cut(lum["today"] + other), 3)})
    return rows


def format_rows(rows: List[dict]) -> str:
    names = list(rows[0]["sky"]) if rows else []
    out = []
    for moment in MOMENTS:
        sel = [r for r in rows if r["moment"] == moment]
        if not sel:
            continue
        out.append(f"{moment} ({sel[0]['hour']:g} h local), streetlights {sel[0]['share']:.0%} of artificial light: "
                   "mag/arcsec^2 (stars overhead)")
        width = {n: max(15, len(n)) + 2 for n in names}
        out.append(f"{'place':18s}" + "".join(f"{n:>{width[n]}s}" for n in names) + f"{'Milky Way needs':>17s}")
        for r in sel:
            cells = "".join(f"{r['sky'][n]['msas']:.2f} ({r['sky'][n]['stars']:4d})".rjust(width[n]) for n in names)
            out.append(f"{r['place']:18s}{cells}{-r['milky_way_cut']:>17.0%}")
        out.append("")
    out.append("Higher mag/arcsec^2 is darker. 'Milky Way needs': change in today's artificial light for the "
               "Milky Way to show at the zenith.")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--share", type=float, default=STREETLIGHT_SHARE_PRIOR,
                    help="streetlights' share of artificial light (Tucson prior)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        rows = packages(share=a.share)
    except ValueError as e:
        print(f"sky_packages: error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(rows, indent=2) if a.json else format_rows(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
