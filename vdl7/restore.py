"""Choose complete source interventions against receptor-specific sky budgets.

An exact, bounded multiple-choice search. Contributions and intervention effects
are supplied evidence/assumptions, not discovered facts. No hardware commands.

Physics. Within one scenario (one atmosphere, one set of reflecting surfaces)
zenith sky luminance is linear in the light emitted: radiative transfer is
linear in its sources, so the contributions of separate sources add exactly.
What one fixed fraction per source cannot express, schema version 2 can:

* the atmosphere and surfaces differ between scenarios, so each scenario has
  its own contributions (`nocturne derive` computes them from aerosol optical
  depth, scattering, reflectance and emitter geometry);
* shielding and re-aiming redistribute light by direction, so one package can
  remove different shares at different places: a remaining fraction per
  observation point, above 1 where light is redirected towards it;
* owners respond to one another and packages share surfaces (a business adds
  floodlights when the street dims), so effects need not add: interaction
  terms on named combinations of options;
* coefficients are uncertain: any value may be a range, and the plan must meet
  every target at the pessimistic end of every range.
"""
from __future__ import annotations

import difflib
import hashlib
import itertools
import json
import math
from decimal import Decimal
from pathlib import Path

MAX_PORTFOLIOS = 1_000_000
EPS = 1e-9
SCHEMA_VERSIONS = (1, 2)
FRACTION_MAX_V2 = 10.0                   # a package may redirect up to 10x a source's light towards one place
MAX_PROBLEMS_SHOWN = 15
LOW, CENTRAL, HIGH = 0, 1, 2             # index into a (low, central, high) value
CASES = {LOW: "optimistic", CENTRAL: "central", HIGH: "pessimistic"}


# ------------------------------------------------- single-value checks (shared with attribution)
def number(value, name, low=0, high=math.inf):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: expected a number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: expected a finite number in [{low}, {high}]")
    return float(value)


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: expected nonempty text")
    return value


def fields(value, required, name):
    if not isinstance(value, dict) or set(value) != set(required.split()):
        raise ValueError(f"{name}: expected fields {required}")


def cents(value, name):
    number(value, name)
    amount = Decimal(str(value)) * 100
    if amount != amount.to_integral_value():
        raise ValueError(f"{name}: use no more than two decimal places")
    return int(amount)


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def read_project(path):
    raw = Path(path).read_text(encoding="utf-8-sig")       # tolerate the BOM spreadsheet tools add
    try:
        return json.loads(raw, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: not valid JSON (line {e.lineno}, column {e.colno}: {e.msg})") from None


# ------------------------------------------------------------- whole-project validation
class ProjectError(ValueError):
    """Every problem found in a project, each with the path of the field."""

    def __init__(self, problems):
        self.problems = list(problems)
        n = len(self.problems)
        lines = [f"  - {p}: {m}" if p else f"  - {m}" for p, m in self.problems[:MAX_PROBLEMS_SHOWN]]
        if n > MAX_PROBLEMS_SHOWN:
            lines.append(f"  ... and {n - MAX_PROBLEMS_SHOWN} more")
        super().__init__(f"{n} problem{'' if n == 1 else 's'} in the project:\n" + "\n".join(lines))


def _kind(value):
    if value is None:
        return "nothing (null)"
    if isinstance(value, bool):
        return "true/false"
    if isinstance(value, str):
        return f"text {value!r}"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "an object"
    return repr(value)


def _bound(x):
    return "infinity" if x == math.inf else "-infinity" if x == -math.inf else f"{x:g}"


_MISSING = object()                      # an absent field: reported once, as missing


class _Checker:
    def __init__(self):
        self.problems = []
        self.version = 2

    def add(self, path, message):
        self.problems.append((path, message))

    def fields(self, value, required, optional, path):
        if not isinstance(value, dict):
            self.add(path, f"expected an object, got {_kind(value)}")
            return False
        missing = [k for k in required if k not in value]
        if missing:
            self.add(path, f"missing field{'s' if len(missing) > 1 else ''}: {', '.join(missing)}")
        for key in value:
            if key not in required and key not in optional:
                close = difflib.get_close_matches(str(key), list(required) + list(optional), n=1)
                self.add(path, f"unknown field {key!r}" + (f"; did you mean {close[0]!r}?" if close else ""))
        return not missing

    def text(self, value, path):
        if value is _MISSING:
            return None
        if isinstance(value, str) and not value.strip():
            self.add(path, "required: cannot be blank")
            return None
        if not isinstance(value, str):
            self.add(path, f"expected text, got {_kind(value)}")
            return None
        return value

    def flag(self, value, path):
        if value is _MISSING:
            return None
        if type(value) is not bool:
            self.add(path, f"must be true or false, got {_kind(value)}")
            return None
        return value

    def number(self, value, path, low=0.0, high=math.inf):
        if value is _MISSING:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self.add(path, f"expected a number, got {_kind(value)}")
            return None
        if not math.isfinite(value) or not low <= value <= high:
            self.add(path, f"expected a finite number from {_bound(low)} to {_bound(high)}, got {value!r}")
            return None
        return float(value)

    def cents(self, value, path):
        if self.number(value, path) is None:
            return None
        amount = Decimal(str(value)) * 100
        if amount != amount.to_integral_value():
            self.add(path, f"use no more than two decimal places, got {value!r}")
            return None
        return int(amount)

    def ranged(self, value, path, low=0.0, high=math.inf):
        """A number, [low, high] or [low, central, high] -> (low, central, high)."""
        if value is _MISSING:
            return None
        if isinstance(value, list):
            if self.version < 2:
                self.add(path, "ranges need schema_version 2")
                return None
            if len(value) not in (2, 3):
                self.add(path, "a range is [low, high] or [low, central, high]")
                return None
            vals = [self.number(v, f"{path}[{i}]", low, high) for i, v in enumerate(value)]
            if None in vals:
                return None
            if any(a > b for a, b in zip(vals, vals[1:])):
                self.add(path, f"a range must not decrease, got {value}")
                return None
            return (vals[0], vals[1] if len(vals) == 3 else (vals[0] + vals[-1]) / 2, vals[-1])
        v = self.number(value, path, low, high)
        return None if v is None else (v, v, v)

    def names(self, value, expected, path, noun):
        """Check that an object names every expected key exactly."""
        if value is _MISSING:
            return False
        if not isinstance(value, dict):
            self.add(path, f"expected an object naming every {noun}, got {_kind(value)}")
            return False
        missing = [k for k in expected if k not in value]
        unknown = [k for k in value if k not in expected]
        if missing or unknown:
            detail = "; ".join(part for part in (f"missing: {', '.join(missing)}" if missing else "",
                                                 f"unknown: {', '.join(map(str, unknown))}" if unknown else "") if part)
            self.add(path, f"must name every {noun} exactly ({detail})")
            return False
        return True

    def per_receptor(self, value, receptors, path, low, high, uniform_ok):
        """{receptor: value} for every receptor, or (where allowed) one value for all."""
        if value is _MISSING:
            return None
        if isinstance(value, dict):
            if uniform_ok and self.version < 2:
                self.add(path, "values per observation point need schema_version 2")
                return None
            if not self.names(value, receptors, path, "observation point"):
                return None
            out = {r: self.ranged(value[r], f"{path}.{r}", low, high) for r in receptors}
            return None if None in out.values() else out
        if not uniform_ok:
            self.add(path, f"expected an object naming every observation point, got {_kind(value)}")
            return None
        v = self.ranged(value, path, low, high)
        return None if v is None else dict.fromkeys(receptors, v)

    def indexed(self, values, path, noun):
        if values is _MISSING:
            return {}
        if not isinstance(values, list) or not values:
            self.add(path, f"expected a nonempty list of {noun}s, got {_kind(values)}")
            return {}
        out = {}
        for i, value in enumerate(values):
            if not isinstance(value, dict):
                self.add(f"{path}[{i}]", f"each {noun} must be an object, got {_kind(value)}")
                continue
            key = value.get("id")
            if not isinstance(key, str) or not key.strip():
                self.add(f"{path}[{i}].id", f"expected nonempty text, got {_kind(key)}")
                continue
            if key in out:
                self.add(f"{path}[{i}]", f"duplicate id {key!r}")
                continue
            out[key] = value
        return out


PROJECT_FIELDS = ("schema_version", "title", "synthetic", "evidence", "budget_usd", "receptors", "sources", "scenarios")
PROJECT_OPTIONAL = ("interactions", "provenance")
SOURCE_FIELDS = ("id", "label", "owner", "authorized", "minimum_service_fraction", "options")
OPTION_FIELDS = ("id", "label", "cost_usd", "service_fraction", "reviewed", "remaining_fraction", "evidence")
SCENARIO_FIELDS = ("id", "label", "unmanaged_mcd_m2", "contributions_mcd_m2")
INTERACTION_FIELDS = ("id", "label", "when", "delta_mcd_m2", "evidence")


def validate(project):
    """Check a project and return its normalized model; raise ProjectError
    listing every problem found, each with the path of the field."""
    ck = _Checker()
    if not ck.fields(project, PROJECT_FIELDS, PROJECT_OPTIONAL, "project"):
        if not isinstance(project, dict):
            raise ProjectError(ck.problems)
    version = project.get("schema_version", _MISSING)
    if version is _MISSING:
        pass
    elif type(version) is not int or version not in SCHEMA_VERSIONS:
        ck.add("schema_version", f"must be {' or '.join(map(str, SCHEMA_VERSIONS))}, got {_kind(version)}")
    else:
        ck.version = version
    if ck.version < 2:
        for key in PROJECT_OPTIONAL:
            if key in project:
                ck.add(key, "needs schema_version 2")
    model = {"version": ck.version, "title": ck.text(project.get("title", _MISSING), "title"),
             "synthetic": ck.flag(project.get("synthetic", _MISSING), "synthetic"),
             "evidence": ck.text(project.get("evidence", _MISSING), "evidence"),
             "budget_cents": ck.cents(project.get("budget_usd", _MISSING), "budget_usd"),
             "provenance": project.get("provenance"), "receptors": {}, "sources": {}, "scenarios": {},
             "interactions": [], "ranged": 0}
    if "provenance" in project and not isinstance(project["provenance"], dict):
        ck.add("provenance", f"expected an object, got {_kind(project['provenance'])}")
    receptors = ck.indexed(project.get("receptors", _MISSING), "receptors", "observation point")
    sources = ck.indexed(project.get("sources", _MISSING), "sources", "source")
    scenarios = ck.indexed(project.get("scenarios", _MISSING), "scenarios", "scenario")
    rids, sids, scids = sorted(receptors), sorted(sources), sorted(scenarios)
    fraction_max = 1.0 if ck.version < 2 else FRACTION_MAX_V2

    for rid, r in receptors.items():
        path = f"receptors[{rid}]"
        ck.fields(r, ("id", "label", "target_mcd_m2"), (), path)
        model["receptors"][rid] = {"label": ck.text(r.get("label", _MISSING), f"{path}.label"),
                                   "target": ck.number(r.get("target_mcd_m2", _MISSING), f"{path}.target_mcd_m2")}

    for scid, sc in scenarios.items():
        path = f"scenarios[{scid}]"
        ck.fields(sc, SCENARIO_FIELDS, (), path)
        entry = {"label": ck.text(sc.get("label", _MISSING), f"{path}.label"), "contrib": {}}
        entry["unmanaged"] = ck.per_receptor(sc.get("unmanaged_mcd_m2", _MISSING), rids, f"{path}.unmanaged_mcd_m2",
                                             0.0, math.inf, uniform_ok=False)
        contributions = sc.get("contributions_mcd_m2", _MISSING)
        if ck.names(contributions, sids, f"{path}.contributions_mcd_m2", "source"):
            for sid in sids:
                entry["contrib"][sid] = ck.per_receptor(contributions[sid], rids, f"{path}.contributions_mcd_m2.{sid}",
                                                        0.0, math.inf, uniform_ok=False)
        model["scenarios"][scid] = entry

    for sid, s in sources.items():
        path = f"sources[{sid}]"
        ck.fields(s, SOURCE_FIELDS, (), path)
        entry = {"label": ck.text(s.get("label", _MISSING), f"{path}.label"), "owner": ck.text(s.get("owner", _MISSING), f"{path}.owner"),
                 "authorized": ck.flag(s.get("authorized", _MISSING), f"{path}.authorized"),
                 "floor": ck.number(s.get("minimum_service_fraction", _MISSING), f"{path}.minimum_service_fraction", high=1),
                 "options": {}}
        for oid, o in ck.indexed(s.get("options", _MISSING), f"{path}.options", "option").items():
            opath = f"{path}.options[{oid}]"
            if oid == "keep":
                ck.add(opath, "option id 'keep' is reserved for the unchanged baseline")
                continue
            ck.fields(o, OPTION_FIELDS, (), opath)
            option = {"label": ck.text(o.get("label", _MISSING), f"{opath}.label"),
                      "evidence": ck.text(o.get("evidence", _MISSING), f"{opath}.evidence"),
                      "cost_cents": ck.cents(o.get("cost_usd", _MISSING), f"{opath}.cost_usd"),
                      "service": ck.number(o.get("service_fraction", _MISSING), f"{opath}.service_fraction", high=1),
                      "reviewed": ck.flag(o.get("reviewed", _MISSING), f"{opath}.reviewed"), "fraction": {}}
            fractions = o.get("remaining_fraction", _MISSING)
            if ck.names(fractions, scids, f"{opath}.remaining_fraction", "scenario"):
                for scid in scids:
                    option["fraction"][scid] = ck.per_receptor(fractions[scid], rids, f"{opath}.remaining_fraction.{scid}",
                                                               0.0, fraction_max, uniform_ok=True)
            entry["options"][oid] = option
        model["sources"][sid] = entry

    interactions = project.get("interactions", [])
    if "interactions" in project and not isinstance(interactions, list):
        ck.add("interactions", f"expected a list, got {_kind(interactions)}")
        interactions = []
    seen = set()
    for i, k in enumerate(interactions):
        path = f"interactions[{i}]"
        if not ck.fields(k, INTERACTION_FIELDS, (), path):
            continue
        kid = ck.text(k["id"], f"{path}.id")
        if kid in seen:
            ck.add(path, f"duplicate id {kid!r}")
        seen.add(kid)
        path = f"interactions[{kid}]" if kid else path
        when, conditions = k["when"], {}
        if not isinstance(when, dict) or not when:
            ck.add(f"{path}.when", "expected an object {source: option or [options]} naming at least one source")
        else:
            for sid, wanted in when.items():
                if sid not in sources:
                    ck.add(f"{path}.when", f"unknown source {sid!r}")
                    continue
                wanted = wanted if isinstance(wanted, list) else [wanted]
                if not all(isinstance(w, str) for w in wanted):
                    ck.add(f"{path}.when.{sid}", "expected an option id, or a list of option ids")
                    continue
                listed = sources[sid].get("options")
                known = {"keep", *(o.get("id") for o in (listed if isinstance(listed, list) else []) if isinstance(o, dict))}
                bad = [w for w in wanted if w not in known]
                if not wanted:
                    ck.add(f"{path}.when.{sid}", "name at least one option (or 'keep'), or leave this source out of the condition")
                    continue
                if bad:
                    ck.add(f"{path}.when.{sid}", f"unknown option {', '.join(map(repr, bad))}; "
                                                 f"known: {', '.join(sorted(map(str, known)))}")
                    continue
                conditions[sid] = frozenset(wanted)
        delta = {}
        if ck.names(k["delta_mcd_m2"], scids, f"{path}.delta_mcd_m2", "scenario"):
            for scid in scids:
                delta[scid] = ck.per_receptor(k["delta_mcd_m2"][scid], rids, f"{path}.delta_mcd_m2.{scid}",
                                              -math.inf, math.inf, uniform_ok=True)
        model["interactions"].append({"id": kid, "label": ck.text(k["label"], f"{path}.label"),
                                      "evidence": ck.text(k["evidence"], f"{path}.evidence"),
                                      "when": conditions, "delta": delta})
    if ck.problems:
        raise ProjectError(ck.problems)

    def count(values):
        return sum(1 for v in values if v[LOW] != v[HIGH])
    for sc in model["scenarios"].values():
        model["ranged"] += count(sc["unmanaged"].values()) + sum(count(c.values()) for c in sc["contrib"].values())
    for s in model["sources"].values():
        for o in s["options"].values():
            model["ranged"] += sum(count(f.values()) for f in o["fraction"].values())
    for k in model["interactions"]:
        model["ranged"] += sum(count(d.values()) for d in k["delta"].values())
    return model


def check(project):
    """Problems that stop a plan, then warnings a planner should read."""
    try:
        m = validate(project)
    except ProjectError as e:
        return {"ok": False, "problems": [{"path": p, "message": msg} for p, msg in e.problems], "warnings": []}
    try:                                             # what `restore` would refuse, `check` refuses too
        if any(v[HIGH] < 0 for k in m["interactions"] for d in k["delta"].values() for v in d.values()):
            _search(m, 2 ** 62, HIGH)                # a synergy might remove more light than exists: look
        else:
            _search(m, 2 ** 62, HIGH, enumerate_portfolios=False)
    except ProjectError as e:
        return {"ok": False, "problems": [{"path": p, "message": msg} for p, msg in e.problems], "warnings": []}
    except ValueError as e:
        return {"ok": False, "problems": [{"path": "sources", "message": str(e)}], "warnings": []}
    warnings = []

    def warn(path, message):
        warnings.append({"path": path, "message": message})

    if m["synthetic"]:
        warn("synthetic", "marked synthetic: results demonstrate the software and are not a plan")
    for sid, s in sorted(m["sources"].items()):
        if not s["authorized"]:
            warn(f"sources[{sid}].authorized", "the owner has not authorized changes: its light counts, its options are excluded")
        if all(v[HIGH] == 0 for sc in m["scenarios"].values() for v in sc["contrib"][sid].values()):
            warn(f"sources[{sid}]", "contributes no light at any observation point, so none of its options can help")
        for oid, o in sorted(s["options"].items()):
            path = f"sources[{sid}].options[{oid}]"
            if not o["reviewed"]:
                warn(f"{path}.reviewed", "not reviewed: excluded until its service review is recorded")
            if o["service"] < s["floor"]:
                warn(f"{path}.service_fraction", "below the source's declared service floor: excluded")
            if all(v[LOW] >= 1 for f in o["fraction"].values() for v in f.values()):
                warn(f"{path}.remaining_fraction", "never removes light anywhere; only an interaction could make it worth choosing")
    for scid, sc in sorted(m["scenarios"].items()):
        for rid, r in sorted(m["receptors"].items()):
            unmanaged = sc["unmanaged"][rid][HIGH]
            if unmanaged > r["target"] + EPS:
                warn(f"scenarios[{scid}].unmanaged_mcd_m2.{rid}",
                     f"unmanaged light alone ({unmanaged:.3f} mcd/m²) exceeds the {r['target']:.3f} target at {r['label']}: "
                     "no listed source can meet it; add the owners of that light or revise the target")
    if m["ranged"]:
        warn("", f"{m['ranged']} value{'s are' if m['ranged'] > 1 else ' is a'} range{'s' if m['ranged'] > 1 else ''}: "
                 "targets are checked at the pessimistic end of every range")
    return {"ok": True, "problems": [], "warnings": warnings}


# ---------------------------------------------------------------------- the search
def _axes(m):
    return [(scid, rid) for scid in sorted(m["scenarios"]) for rid in sorted(m["receptors"])]


def _eligibility(m):
    """Options the planner may use, and the reasons it may not use the others."""
    allowed, excluded = {}, []
    for sid in sorted(m["sources"]):
        s = m["sources"][sid]
        allowed[sid] = []
        for oid in sorted(s["options"]):
            o = s["options"][oid]
            reasons = []
            if not s["authorized"]:
                reasons.append("owner authorization missing")
            if not o["reviewed"]:
                reasons.append("service review missing")
            if o["service"] < s["floor"]:
                reasons.append("below declared service floor")
            if reasons:
                excluded.append({"source": sid, "option": oid, "reasons": reasons})
            else:
                allowed[sid].append(oid)
    return allowed, excluded


def _terms(m, axes, selection, case):
    """Per-axis luminance terms of one selection {source: option}: unmanaged,
    each source's remaining light, each active interaction."""
    terms = {"unmanaged": [m["scenarios"][scid]["unmanaged"][rid][case] for scid, rid in axes]}
    for sid, oid in selection.items():
        contrib = m["scenarios"]
        if oid == "keep":
            terms[sid] = [contrib[scid]["contrib"][sid][rid][case] for scid, rid in axes]
        else:
            fraction = m["sources"][sid]["options"][oid]["fraction"]
            terms[sid] = [contrib[scid]["contrib"][sid][rid][case] * fraction[scid][rid][case] for scid, rid in axes]
    for k in m["interactions"]:
        if all(selection.get(sid) in oids for sid, oids in k["when"].items()):
            terms["interaction:" + k["id"]] = [k["delta"][scid][rid][case] for scid, rid in axes]
    return terms


def _total(terms, n):
    # Sequential addition, as the search does: sum() compensates on Python 3.12+ only.
    out = [0.0] * n
    for values in terms.values():
        out = [a + b for a, b in zip(out, values)]
    return out


def _rank(choice):
    return (choice["option"] != "keep", choice["option"])


def _search(m, budget, case, enumerate_portfolios=True):
    """The best portfolio for one case of the values. With enumerate_portfolios
    False, stop after the size check (for `check`)."""
    axes = _axes(m)
    n = len(axes)
    targets = [m["receptors"][rid]["target"] for _, rid in axes]
    allowed, excluded = _eligibility(m)
    sids = sorted(m["sources"])
    interacting = {sid for k in m["interactions"] for sid in k["when"]}
    unmanaged = [m["scenarios"][scid]["unmanaged"][rid][case] for scid, rid in axes]
    baseline = _total(_terms(m, axes, dict.fromkeys(sids, "keep"), case), n)
    floor = unmanaged[:]
    groups = []
    for sid in sids:
        choices = []
        for oid in ["keep"] + allowed[sid]:
            remaining = _terms(m, axes, {sid: oid}, case)[sid]
            cost = 0 if oid == "keep" else m["sources"][sid]["options"][oid]["cost_cents"]
            choices.append({"source": sid, "option": oid, "cost_cents": cost, "remaining": remaining})
        floor = [v + min(o["remaining"][i] for o in choices) for i, v in enumerate(floor)]
        if sid not in interacting:
            # Drop strictly dominated options after eligibility. On an exact tie "keep" wins (a change
            # that costs nothing and does nothing is not an action), then the lower ID.
            # A source in an interaction keeps every option: a dearer, brighter one may unlock a synergy.
            choices = [o for o in choices if not any(
                p is not o and p["cost_cents"] <= o["cost_cents"]
                and all(a <= b for a, b in zip(p["remaining"], o["remaining"]))
                and (p["cost_cents"] < o["cost_cents"] or p["remaining"] != o["remaining"] or _rank(p) < _rank(o))
                for p in choices)]
        groups.append(choices)
    deltas = []
    for k in m["interactions"]:
        vector = [k["delta"][scid][rid][case] for scid, rid in axes]
        floor = [f + min(0.0, d) for f, d in zip(floor, vector)]
        deltas.append(([(sids.index(sid), oids) for sid, oids in k["when"].items()], vector, k["id"]))
    combinations = math.prod(len(g) for g in groups)
    if combinations > MAX_PORTFOLIOS:
        raise ValueError(f"{combinations:,} portfolios exceeds exact-search limit {MAX_PORTFOLIOS:,}; "
                         "combine sources into reviewed packages or reduce alternatives; no approximate result was produced")
    if not enumerate_portfolios:
        return {"combinations": combinations}
    best, best_key, count, cheapest_feasible = None, None, 0, None
    for portfolio in itertools.product(*groups):
        cost = sum(o["cost_cents"] for o in portfolio)
        remaining = [unmanaged[i] + sum(o["remaining"][i] for o in portfolio) for i in range(n)]
        active = [kid for conditions, vector, kid in deltas
                  if all(portfolio[g]["option"] in oids for g, oids in conditions)]
        for conditions, vector, kid in deltas:
            if kid in active:
                remaining = [a + b for a, b in zip(remaining, vector)]
        if active and min(remaining) < -EPS:
            raise ProjectError([("interactions", f"{', '.join(active)} remove more light than the sources emit "
                                 f"({CASES[case]} values give {min(remaining):.4f} mcd/m² with "
                                 + ", ".join(f"{o['source']}={o['option']}" for o in portfolio) + ")")])
        feasible = all(v <= t + EPS for v, t in zip(remaining, targets))
        if feasible:
            cheapest_feasible = cost if cheapest_feasible is None else min(cost, cheapest_feasible)
        if cost > budget:
            continue
        count += 1
        progress = min(1.0 if b <= t + EPS else max(0.0, min(1.0, (b - v) / (b - t)))
                       for b, v, t in zip(baseline, remaining, targets))
        key = (0 if feasible else 1, cost if feasible else -progress, sum(remaining), cost,
               tuple(_rank(o) for o in portfolio))
        if best_key is None or key < best_key:
            best_key = key
            best = (portfolio, cost, remaining, feasible, progress)
    portfolio, cost, remaining, feasible, progress = best
    status = "feasible" if feasible else "budget_shortfall" if cheapest_feasible is not None else "outside_available_actions"
    return {"axes": axes, "targets": targets, "baseline": baseline, "floor": floor, "excluded": excluded,
            "selection": {o["source"]: o["option"] for o in portfolio}, "cost": cost, "remaining": remaining,
            "feasible": feasible, "progress": progress, "status": status, "count": count,
            "combinations": combinations, "cheapest_feasible": cheapest_feasible}


def _target_status(low, high, target):
    if high <= target + EPS:
        return "met"
    return "uncertain" if low <= target + EPS else "not_met"


def solve(project, budget_usd=None):
    """Cheapest feasible portfolio, else best minimum target completion.

Every scenario/receptor must meet its target; a citywide average cannot hide
one failed place. Options for one source are mutually exclusive complete
packages. 'keep' is always available, including for unconsenting owners.
Where a value is a range the search plans against its pessimistic end, and
also reports what the cheapest plan would be on central values.
"""
    m = validate(project)
    budget = m["budget_cents"] if budget_usd is None else cents(budget_usd, "budget_usd")
    plan = _search(m, budget, HIGH)
    central, central_problem = None, None
    if m["ranged"]:
        try:
            central = _search(m, budget, CENTRAL)
        except ProjectError as e:                    # informational only: the plan stands on pessimistic values
            central_problem = "; ".join(msg for _, msg in e.problems)
    axes, n, selection = plan["axes"], len(plan["axes"]), plan["selection"]
    terms_low = _terms(m, axes, selection, LOW)
    terms_high = _terms(m, axes, selection, HIGH)
    low, high = _total(terms_low, n), _total(terms_high, n)
    base_low = _total(_terms(m, axes, dict.fromkeys(selection, "keep"), LOW), n)
    rows = []
    for i, (scid, rid) in enumerate(axes):
        b, v, t = plan["baseline"][i], plan["remaining"][i], plan["targets"][i]
        term, value = max(((k, vals[i]) for k, vals in terms_high.items()), key=lambda kv: (kv[1], kv[0]))
        rows.append({"scenario": scid, "receptor": rid, "label": m["receptors"][rid]["label"],
                     "baseline_mcd_m2": b, "remaining_mcd_m2": v, "target_mcd_m2": t,
                     "gap_mcd_m2": max(0.0, v - t), "reduction_fraction": (b - v) / b if b else 0.0,
                     "optimistic_floor_without_budget_mcd_m2": plan["floor"][i], "meets_target": v <= t + EPS,
                     "baseline_range_mcd_m2": [base_low[i], b], "remaining_range_mcd_m2": [low[i], high[i]],
                     "target_status": _target_status(low[i], high[i], t),
                     "headroom_fraction": t / v - 1 if v > EPS else None,
                     "dominant_term": {"term": term, "mcd_m2": value}})
    canonical = json.dumps(project, sort_keys=True, separators=(",", ":"), allow_nan=False)
    sources = m["sources"]
    actions = [{"source": sid, "source_label": sources[sid]["label"], "owner": sources[sid]["owner"], "option": oid,
                "label": sources[sid]["options"][oid]["label"], "cost_usd": sources[sid]["options"][oid]["cost_cents"] / 100,
                "evidence": sources[sid]["options"][oid]["evidence"]}
               for sid, oid in sorted(selection.items()) if oid != "keep"]
    uncertainty = {"ranged_values": m["ranged"], "planning_case": "pessimistic end of every range"}
    if central_problem:
        uncertainty["central_plan"] = {"status": "not_computed", "reason": central_problem}
        uncertainty["cost_of_uncertainty_usd"] = None
    if central is not None:
        uncertainty["central_plan"] = {
            "status": central["status"], "cost_usd": central["cost"] / 100,
            "actions": [{"source": s, "option": o} for s, o in sorted(central["selection"].items()) if o != "keep"]}
        uncertainty["cost_of_uncertainty_usd"] = (
            (plan["cost"] - central["cost"]) / 100 if plan["feasible"] and central["feasible"] else None)
    return {"schema_version": 2, "project_schema_version": m["version"], "title": m["title"],
            "synthetic": m["synthetic"], "project_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "status": plan["status"], "solver": "exact enumeration after dominance pruning",
            "candidate_portfolios": plan["combinations"], "portfolios_within_budget": plan["count"],
            "budget_usd": budget / 100, "cost_usd": plan["cost"] / 100,
            "minimum_feasible_cost_usd": None if plan["cheapest_feasible"] is None else plan["cheapest_feasible"] / 100,
            "worst_target_completion": plan["progress"], "receptors": rows, "excluded_options": plan["excluded"],
            "actions": actions, "source_labels": {sid: s["label"] for sid, s in sorted(sources.items())},
            "uncertainty": uncertainty,
            "interactions": [{"id": k["id"], "label": k["label"], "evidence": k["evidence"],
                              "active": "interaction:" + k["id"] in terms_high} for k in m["interactions"]],
            "provenance": m["provenance"],
            "limits": ["Planning result only. No commands are sent to lights.",
                       "Every result is conditional on the supplied contributions and complete action packages.",
                       "Contributions add exactly within one scenario (radiative transfer is linear in its sources); "
                       "the approximations are the scenario set, the supplied coefficients and the declared interactions.",
                       "Scenarios are stress cases, not statistical confidence intervals; ranges are checked at their "
                       "pessimistic end, not given probabilities.",
                       "Service fractions and review flags are declarations, not a photometric safety certification.",
                       "Artificial zenith luminance is not a measure of glare, window trespass, or habitat illuminance.",
                       "Unmanaged light remains in every portfolio; no energy savings or star counts are inferred."]}


def _term_name(term):
    if term == "unmanaged":
        return "unmanaged light"
    if term.startswith("interaction:"):
        return "interaction " + term.split(":", 1)[1]
    return term


def format_plan(result):
    lines = [result["title"], "SYNTHETIC EXAMPLE — not a DC forecast" if result["synthetic"] else "CONDITIONAL MODEL — not a measured outcome",
             f"Status: {result['status']}", f"Selected cost: ${result['cost_usd']:,.2f} / ${result['budget_usd']:,.2f}"]
    minimum = result["minimum_feasible_cost_usd"]
    lines.append("No available portfolio meets every target." if minimum is None else f"Least cost to meet every target: ${minimum:,.2f}")
    for action in result["actions"]:
        lines.append(f"  {action['owner']}: {action['label']} (${action['cost_usd']:,.2f})")
    ranged = result["uncertainty"]["ranged_values"]
    for row in result["receptors"]:
        lo, hi = row["remaining_range_mcd_m2"]
        span = f" (range {lo:.3f}–{hi:.3f})" if ranged and hi - lo > EPS else ""
        status = {"met": "met", "uncertain": "UNCERTAIN: met only at the optimistic end", "not_met": "NOT MET"}[row["target_status"]]
        headroom = row["headroom_fraction"]
        extra = f", {headroom:.0%} headroom" if row["target_status"] == "met" and headroom is not None else ""
        lines.append(f"  {row['scenario']}/{row['receptor']}: {row['baseline_mcd_m2']:.3f} -> "
                     f"{row['remaining_mcd_m2']:.3f} mcd/m²{span}; target {row['target_mcd_m2']:.3f}; {status}{extra}; "
                     f"largest remaining: {_term_name(row['dominant_term']['term'])}")
    active = [k for k in result["interactions"] if k["active"]]
    for k in active:
        lines.append(f"  interaction in effect: {k['label']}")
    u = result["uncertainty"]
    if ranged:
        lines.append(f"{ranged} ranged value{'s' if ranged > 1 else ''}; plan checked at the pessimistic end.")
        if u.get("cost_of_uncertainty_usd") == 0:
            lines.append("The ranges do not change the price: central values give a plan of the same cost.")
        elif u.get("cost_of_uncertainty_usd") is not None:
            lines.append(f"On central values the cheapest plan costs ${u['central_plan']['cost_usd']:,.2f}: "
                         f"uncertainty costs ${u['cost_of_uncertainty_usd']:,.2f}. Measuring the largest terms narrows it.")
    lines.append("Use `nocturne experiment` to preregister a source trial; then measure and re-plan.")
    return "\n".join(lines)
