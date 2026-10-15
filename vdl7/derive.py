"""Derive a restoration project's coefficients from geometry and atmosphere.

A hand-entered "this package leaves 40 % of the light" cannot say how that
share changes with the observer's distance, the haze, the snow, or the
direction the light leaves in. This module computes it instead. Each source
is a set of emitters (position, area, lumens in the assessed window, the
share sent directly upward, the reflectance of what the rest lands on, the
spectrum); each option says what physically changes (output, uplight,
reflectance, spectrum); each condition is an atmosphere and a surface state.
The zenith luminance at every observation point comes from the same
single-scattering model as `nocturne sky` (vdl7.skyglow): Rayleigh and
aerosol scattering with extinction on both legs, direct uplight emitted
evenly over the upper hemisphere, reflected light emitted as a Lambertian
surface. The output is an ordinary schema-2 project for `nocturne restore`,
with a remaining fraction for every option, condition and place.

What this captures that a fixed fraction does not:
* in clear air, removing direct uplight helps distant places more than near
  ones, because low-angle light travels further than light reflected towards
  the zenith; in heavy haze those long low paths are extinguished and the
  advantage peaks a few kilometres out;
* haze brightens the sky near the sources and darkens it far away, so the
  same package removes different shares on clear and hazy nights;
* snow multiplies what surfaces reflect, so shielding the uplight matters
  less and dimming matters more under snow;
* warmer spectra scatter less per lumen, mostly in the molecular term.

What it leaves out (and the provenance block says so): multiple scattering
and Earth curvature (matter beyond about 30 km), terrain and buildings that
block low paths, the real angular distribution of each luminaire (use its
IES file's upward light ratio for `uplight_fraction`), and the absolute
calibration. Ratios between before and after are robust to most of these;
absolute contributions are not, so `calibration_factor` (a number or a
range) scales them, ideally from a sky-quality-meter measurement.
"""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache

from . import spectral
from .restore import _MISSING, FRACTION_MAX_V2, ProjectError, _Checker, validate
from .skyglow import Atmosphere, area_kernel, distance_m

SCHEMA = "nocturne-physical/1"
DEFAULTS = {"aerosol_scale_height_m": 1500.0, "single_scattering_albedo": 0.90, "asymmetry": 0.70,
            "reflectance_multiplier": 1.0}
MAX_REFLECTANCE = 0.95
PHYSICAL_FIELDS = ("schema", "title", "synthetic", "evidence", "budget_usd", "coordinates", "receptors",
                   "conditions", "sources")
PHYSICAL_OPTIONAL = ("interactions", "calibration_factor")
CHANGE_FIELDS = ("output_factor", "uplight_fraction", "reflectance", "spectrum")
LIMITS = ["Single scattering in a plane-parallel atmosphere: no multiple scattering or Earth curvature "
          "(significant beyond about 30 km), no terrain or building obstruction.",
          "Direct uplight is emitted evenly over the upper hemisphere and reflected light as a Lambertian "
          "surface; real luminaires and facades have their own distributions.",
          "Absolute contributions carry the calibration factor; before/after ratios are far less sensitive "
          "to it. Calibrate against measured zenith brightness before relying on absolute values.",
          "Lumens are those emitted during the assessed window; a curfew or booking schedule enters as an output factor."]


@lru_cache(maxsize=32)
def _weights(spectrum):
    return spectral.scatter_weight(spectrum, 4.0), spectral.scatter_weight(spectrum, 1.3)


def _spectrum(ck, value, path):
    name = ck.text(value, path)
    if name is None:
        return None
    try:
        _weights(name)
    except (KeyError, ValueError):
        ck.add(path, f"unknown spectrum {name!r}; use a CCT such as '3000K', or one of: {', '.join(spectral.SPECTRA)}")
        return None
    return name


def _point(ck, value, path, coordinates):
    keys = ("x_m", "y_m") if coordinates == "local_m" else ("lat", "lon")
    bounds = {"x_m": (-200_000, 200_000), "y_m": (-200_000, 200_000), "lat": (-90, 90), "lon": (-180, 180)}
    out = []
    for key in keys:                       # an absent key is already reported as a missing field
        out.append(ck.number(value.get(key, _MISSING), f"{path}.{key}", *bounds[key]))
    return None if None in out else tuple(out)


def read(physical):
    """Check a physical district and return it normalized; raise ProjectError with every problem."""
    ck = _Checker()
    if not ck.fields(physical, PHYSICAL_FIELDS, PHYSICAL_OPTIONAL, "district") and not isinstance(physical, dict):
        raise ProjectError(ck.problems)
    if physical.get("schema", _MISSING) not in (SCHEMA, _MISSING):
        ck.add("schema", f"must be {SCHEMA!r}")
    coordinates = physical.get("coordinates", "local_m")
    if coordinates not in ("local_m", "latlon"):
        ck.add("coordinates", "must be 'local_m' (x_m, y_m in metres) or 'latlon' (lat, lon in degrees)")
        coordinates = "local_m"
    point_fields = ("x_m", "y_m") if coordinates == "local_m" else ("lat", "lon")
    out = {"coordinates": coordinates, "receptors": {}, "conditions": {}, "sources": {}}
    for key in ("title", "evidence"):
        out[key] = ck.text(physical.get(key, _MISSING), key)
    out["synthetic"] = ck.flag(physical.get("synthetic", _MISSING), "synthetic")
    out["budget_usd"] = physical.get("budget_usd", _MISSING)
    ck.cents(out["budget_usd"], "budget_usd")
    out["calibration"] = ck.ranged(physical.get("calibration_factor", 1.0), "calibration_factor", 0.01, 100.0)

    receptors = ck.indexed(physical.get("receptors", _MISSING), "receptors", "observation point")
    rids = sorted(receptors)
    for rid, r in receptors.items():
        path = f"receptors[{rid}]"
        ck.fields(r, ("id", "label", "target_mcd_m2", *point_fields), (), path)
        out["receptors"][rid] = {"label": ck.text(r.get("label", _MISSING), f"{path}.label"),
                                 "target": ck.number(r.get("target_mcd_m2", _MISSING), f"{path}.target_mcd_m2"),
                                 "at": _point(ck, r, path, coordinates)}

    conditions = ck.indexed(physical.get("conditions", _MISSING), "conditions", "condition")
    for cid, c in conditions.items():
        path = f"conditions[{cid}]"
        ck.fields(c, ("id", "label", "aod_550", "unmanaged_mcd_m2"), tuple(DEFAULTS), path)
        params = {"label": ck.text(c.get("label", _MISSING), f"{path}.label"),
                  "aod_550": ck.number(c.get("aod_550", _MISSING), f"{path}.aod_550", 0.0, 5.0),
                  "aerosol_scale_height_m": ck.number(c.get("aerosol_scale_height_m", DEFAULTS["aerosol_scale_height_m"]),
                                                      f"{path}.aerosol_scale_height_m", 100.0, 10_000.0),
                  "single_scattering_albedo": ck.number(c.get("single_scattering_albedo", DEFAULTS["single_scattering_albedo"]),
                                                        f"{path}.single_scattering_albedo", 0.0, 1.0),
                  "asymmetry": ck.number(c.get("asymmetry", DEFAULTS["asymmetry"]), f"{path}.asymmetry", 0.0, 0.95),
                  "reflectance_multiplier": ck.number(c.get("reflectance_multiplier", DEFAULTS["reflectance_multiplier"]),
                                                      f"{path}.reflectance_multiplier", 0.0, 10.0)}
        unmanaged = c.get("unmanaged_mcd_m2", _MISSING)
        if ck.per_receptor(unmanaged, rids, f"{path}.unmanaged_mcd_m2", 0.0, math.inf, uniform_ok=True) is not None:
            params["unmanaged"] = unmanaged
        out["conditions"][cid] = params

    sources = ck.indexed(physical.get("sources", _MISSING), "sources", "source")
    for sid, s in sources.items():
        path = f"sources[{sid}]"
        ck.fields(s, ("id", "label", "owner", "authorized", "minimum_service_fraction", "spectrum", "emitters", "options"),
                  (), path)
        entry = {"label": ck.text(s.get("label", _MISSING), f"{path}.label"),
                 "owner": ck.text(s.get("owner", _MISSING), f"{path}.owner"),
                 "authorized": ck.flag(s.get("authorized", _MISSING), f"{path}.authorized"),
                 "floor": s.get("minimum_service_fraction", _MISSING),
                 "spectrum": _spectrum(ck, s.get("spectrum", _MISSING), f"{path}.spectrum"),
                 "emitters": [], "options": []}
        ck.number(entry["floor"], f"{path}.minimum_service_fraction", high=1)
        emitters = s.get("emitters", _MISSING)
        if emitters is not _MISSING and (not isinstance(emitters, list) or not emitters):
            ck.add(f"{path}.emitters", "expected a nonempty list of emitters")
        for i, e in enumerate(emitters if isinstance(emitters, list) else []):
            epath = f"{path}.emitters[{i}]"
            if not ck.fields(e, ("lumens", "uplight_fraction", "reflectance", *point_fields), ("radius_m", "label"), epath):
                continue
            entry["emitters"].append({
                "at": _point(ck, e, epath, coordinates),
                "radius_m": ck.number(e.get("radius_m", 50.0), f"{epath}.radius_m", 10.0, 5000.0),
                "lumens": ck.number(e["lumens"], f"{epath}.lumens", 0.0, 1e10),
                "uplight": ck.number(e["uplight_fraction"], f"{epath}.uplight_fraction", 0.0, 1.0),
                "reflectance": ck.number(e["reflectance"], f"{epath}.reflectance", 0.0, MAX_REFLECTANCE)})
        options = s.get("options", _MISSING)
        if options is not _MISSING and (not isinstance(options, list) or not options):
            ck.add(f"{path}.options", "expected a nonempty list of options")
        for o in options if isinstance(options, list) else []:
            oid = o.get("id") if isinstance(o, dict) else None
            opath = f"{path}.options[{oid}]"
            if not ck.fields(o, ("id", "label", "cost_usd", "service_fraction", "reviewed", "evidence", "change"), (), opath):
                continue
            change = o["change"]
            if not ck.fields(change, (), CHANGE_FIELDS, f"{opath}.change"):
                continue
            if not change:
                ck.add(f"{opath}.change", f"name at least one of: {', '.join(CHANGE_FIELDS)}")
            parsed = {}
            if "output_factor" in change:
                parsed["output_factor"] = ck.number(change["output_factor"], f"{opath}.change.output_factor", 0.0, 10.0)
            if "uplight_fraction" in change:
                parsed["uplight"] = ck.number(change["uplight_fraction"], f"{opath}.change.uplight_fraction", 0.0, 1.0)
            if "reflectance" in change:
                parsed["reflectance"] = ck.number(change["reflectance"], f"{opath}.change.reflectance", 0.0, MAX_REFLECTANCE)
            if "spectrum" in change:
                parsed["spectrum"] = _spectrum(ck, change["spectrum"], f"{opath}.change.spectrum")
            entry["options"].append({"raw": {k: v for k, v in o.items() if k != "change"}, "change": parsed})
        out["sources"][sid] = entry
    out["interactions"] = physical.get("interactions")
    if ck.problems:
        raise ProjectError(ck.problems)
    return out


def _distance(a, b, coordinates):
    if coordinates == "local_m":
        return math.hypot(a[0] - b[0], a[1] - b[1])
    return distance_m(a[0], a[1], b[0], b[1])


def _atmosphere(c):
    return Atmosphere(aod_550=c["aod_550"], aerosol_h_m=c["aerosol_scale_height_m"],
                      ssa=c["single_scattering_albedo"], hg_g=c["asymmetry"])


def luminance_mcd(emitters, spectrum, condition, at, coordinates, change=None):
    """Artificial zenith luminance (mcd/m^2) at `at` from a source's emitters,
    after an optional physical change."""
    change = change or {}
    atm = _atmosphere(condition)
    w_r, w_a = _weights(change.get("spectrum", spectrum))
    total = 0.0
    for e in emitters:
        lumens = e["lumens"] * change.get("output_factor", 1.0)
        uplight = change.get("uplight", e["uplight"])
        reflectance = min(MAX_REFLECTANCE, change.get("reflectance", e["reflectance"]) * condition["reflectance_multiplier"])
        up_iso, up_lambert = lumens * uplight, reflectance * lumens * (1.0 - uplight)
        if up_iso <= 0 and up_lambert <= 0:
            continue
        d = _distance(at, e["at"], coordinates)
        for emission, up in (("iso", up_iso), ("lambert", up_lambert)):
            if up > 0:
                total += up * (area_kernel(d, e["radius_m"], emission, "R", atm) * w_r
                               + area_kernel(d, e["radius_m"], emission, "A", atm) * w_a)
    return 1000.0 * total


def _round(x):
    return float(f"{x:.6g}")


def derive(physical):
    """A schema-2 restoration project computed from a physical district."""
    d = read(physical)
    rids, cids = sorted(d["receptors"]), sorted(d["conditions"])
    low, central, high = d["calibration"]

    def calibrated(v):
        return _round(v * low) if low == high else [_round(v * low), _round(v * central), _round(v * high)]

    before = {(sid, cid, rid): luminance_mcd(s["emitters"], s["spectrum"], d["conditions"][cid],
                                             d["receptors"][rid]["at"], d["coordinates"])
              for sid, s in d["sources"].items() for cid in cids for rid in rids}
    scenarios, sources, problems = [], [], []
    for cid in cids:
        unmanaged = d["conditions"][cid]["unmanaged"]
        scenarios.append({"id": cid, "label": d["conditions"][cid]["label"],
                          "unmanaged_mcd_m2": unmanaged if isinstance(unmanaged, dict) else dict.fromkeys(rids, unmanaged),
                          "contributions_mcd_m2": {sid: {rid: calibrated(before[sid, cid, rid]) for rid in rids}
                                                   for sid in sorted(d["sources"])}})
    for sid, s in sorted(d["sources"].items()):
        options = []
        for o in s["options"]:
            fractions = {}
            for cid in cids:
                fractions[cid] = {}
                for rid in rids:
                    after = luminance_mcd(s["emitters"], s["spectrum"], d["conditions"][cid], d["receptors"][rid]["at"],
                                          d["coordinates"], o["change"])
                    b = before[sid, cid, rid]
                    f = after / b if b > 1e-12 else 1.0
                    if f > FRACTION_MAX_V2:
                        problems.append((f"sources[{sid}].options[{o['raw']['id']}].change",
                                         f"multiplies the light at {rid} under {cid} by {f:.1f}, more than {FRACTION_MAX_V2:g}x"))
                    fractions[cid][rid] = _round(f)
                if len(set(fractions[cid].values())) == 1:            # same everywhere: say so plainly
                    fractions[cid] = next(iter(fractions[cid].values()))
            options.append({**o["raw"], "remaining_fraction": fractions})
        sources.append({"id": sid, "label": s["label"], "owner": s["owner"], "authorized": s["authorized"],
                        "minimum_service_fraction": s["floor"], "options": options})
    if problems:
        raise ProjectError(problems)
    canonical = json.dumps(physical, sort_keys=True, separators=(",", ":"), allow_nan=False)
    project = {"schema_version": 2, "title": d["title"], "synthetic": d["synthetic"], "evidence": d["evidence"],
               "budget_usd": d["budget_usd"],
               "receptors": [{"id": rid, "label": d["receptors"][rid]["label"], "target_mcd_m2": d["receptors"][rid]["target"]}
                             for rid in rids],
               "sources": sources, "scenarios": scenarios,
               "provenance": {"derived_by": "nocturne derive", "input_schema": SCHEMA,
                              "input_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
                              "method": "single-scattering zenith luminance (vdl7.skyglow kernels), photopic SQM-like band",
                              "calibration_factor": physical.get("calibration_factor", 1.0),
                              "conditions": {cid: {k: v for k, v in d["conditions"][cid].items() if k not in ("label", "unmanaged")}
                                             for cid in cids},
                              "limits": LIMITS}}
    if d["interactions"] is not None:
        project["interactions"] = d["interactions"]
    validate(project)                          # the result must be a project restore accepts
    return project


def format_derivation(project):
    """A short table of what was derived, for the terminal."""
    lines = [project["title"], "Derived contributions (mcd/m²) and remaining fractions per observation point:"]
    rids = [r["id"] for r in project["receptors"]]
    for sc in project["scenarios"]:
        lines.append(f"  {sc['id']}: " + "  ".join(f"{r}" for r in rids))
        for sid, row in sc["contributions_mcd_m2"].items():
            cells = [(f"{v[0]:.3f}–{v[-1]:.3f}" if isinstance(v, list) else f"{v:.3f}") for v in (row[r] for r in rids)]
            lines.append(f"    {sid:16s} " + "  ".join(cells))
    for s in project["sources"]:
        for o in s["options"]:
            parts = []
            for cid, f in o["remaining_fraction"].items():
                parts.append(f"{cid} {f:.2f}" if not isinstance(f, dict)
                             else f"{cid} " + "/".join(f"{f[r]:.2f}" for r in rids))
            lines.append(f"  {s['id']}/{o['id']}: leaves " + "; ".join(parts))
    lines.append("Next: nocturne restore <this file>. Coefficients are modelled, not measured; see provenance.limits.")
    return "\n".join(lines)
