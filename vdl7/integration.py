"""From exported programmes to an import someone is accountable for.

A node that scanned in as "registered" is not proof that a city's central
management system will accept Nocturne's programmes, that the contract lets
anyone change them, or that the dimmed levels are safe on that street. This
module makes those gaps explicit and checkable:

* `check_program` / `adapt_program`: compare each programme with a declared
  controller capability profile (steps per programme, time resolution, level
  granularity, minimum stable level, dusk/dawn source, programme slots).
  Adaptation is allowed in one direction only: every adapted programme is at
  least as bright as the exported one at every minute of the night, so a
  controller limit can cost energy but never light. What cannot be adapted
  that way (a level the node cannot reach, too many programmes, no dusk/dawn
  source) is refused.
* `readiness_record` / `evaluate_readiness`: a record of the human gates
  (contract authority, CMS access, equipment test, photometric review, High-
  Injury Network assignment, rollback, operations) bound by SHA-256 to the
  exact files reviewed. Change a file after approval and the record fails.
* `reconcile`: compare what the CMS reports it holds with what was meant:
  a missing segment or any minute darker than intended is an error.

None of this talks to a CMS or a light. It produces evidence for the people
who do.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path

CAPS_SCHEMA = "nocturne-controller-capabilities/1"
READINESS_SCHEMA = "nocturne-readiness/1"
RESOLUTIONS = (1, 5, 10, 15, 20, 30, 60)
NIGHT_START = 12 * 60                        # minutes are counted from noon so a night never wraps
NOMINAL_DUSK, NOMINAL_DAWN = 18 * 60, 31 * 60   # 18:00 and 07:00 next day: weights for choosing merges only
CAPS_FIELDS = ("schema", "name", "source", "verified", "dusk_dawn", "max_steps_per_program", "time_resolution_min",
               "min_level_pct", "max_level_pct", "level_step_pct", "max_programs")

GATES = [
    ("authority", "Contract authority",
     "Under the streetlight contract, who may change schedules on these nodes, and has that person agreed to this change?"),
    ("cms-access", "CMS access",
     "Does the agreement with the CMS operator allow programme import and readback for these nodes, and who performs them?"),
    ("equipment", "Equipment test",
     "Has a bench or field test on each node family confirmed it accepts these programmes (steps, times, levels, dusk and "
     "dawn source) and keeps them through a network loss, and that the driver delivers the requested levels (metered)?"),
    ("photometric", "Photometric review",
     "Has a licensed lighting engineer confirmed every dimmed level meets the applicable standard for each road class "
     "(for example ANSI/IES RP-8), including transitions?"),
    ("hin", "High-Injury Network",
     "Have the High-Injury Network segments in this wave been identified from the city's list and given their hin/ programmes?"),
    ("rollback", "Rollback",
     "Is there a tested way to return every node in this wave to its previous programme within one night?"),
    ("operations", "Operations",
     "Is a 311 'street too dark' route to an operator override staffed, and is the crash brake scheduled before the next wave?"),
]
GATE_STATUSES = ("pending", "approved", "not_applicable")


# ------------------------------------------------------------- capability profiles
def read_capabilities(caps):
    """Check a controller capability profile; return it, or raise ValueError listing every problem."""
    problems = []
    if not isinstance(caps, dict):
        raise ValueError("controller profile: expected a JSON object")
    missing = [k for k in CAPS_FIELDS if k not in caps]
    unknown = [k for k in caps if k not in CAPS_FIELDS]
    if missing:
        problems.append(f"missing: {', '.join(missing)}")
    if unknown:
        problems.append(f"unknown fields: {', '.join(map(str, unknown))}")
    if caps.get("schema") != CAPS_SCHEMA:
        problems.append(f"schema must be {CAPS_SCHEMA!r}")
    for key in ("name", "source"):
        if key in caps and (not isinstance(caps[key], str) or not caps[key].strip()):
            problems.append(f"{key}: expected nonempty text")
    if "verified" in caps and type(caps["verified"]) is not bool:
        problems.append("verified: must be true or false")
    if "dusk_dawn" in caps:
        dd = caps["dusk_dawn"]
        if not isinstance(dd, list) or not dd or any(v not in ("astronomical", "photocell") for v in dd):
            problems.append("dusk_dawn: a nonempty list of 'astronomical' and/or 'photocell'")

    def integer(key, low, high):
        v = caps.get(key)
        if key in caps and (type(v) is not int or not low <= v <= high):
            problems.append(f"{key}: expected a whole number from {low} to {high}")

    integer("max_steps_per_program", 1, 96)
    integer("min_level_pct", 0, 100)
    integer("max_level_pct", 1, 100)
    integer("level_step_pct", 1, 50)
    integer("max_programs", 1, 100_000)
    if "time_resolution_min" in caps and caps["time_resolution_min"] not in RESOLUTIONS:
        problems.append(f"time_resolution_min: one of {', '.join(map(str, RESOLUTIONS))}")
    if not problems and caps["min_level_pct"] > caps["max_level_pct"]:
        problems.append("min_level_pct is above max_level_pct")
    if not problems and caps["max_level_pct"] % caps["level_step_pct"]:
        problems.append("max_level_pct must be a multiple of level_step_pct")
    if problems:
        raise ValueError("controller profile: " + "; ".join(problems))
    return caps


def _minute(at):
    """'HH:MM' -> minutes since noon (after-midnight times land the next day)."""
    m = re.fullmatch(r"(\d{2}):(\d{2})", at)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"step time {at!r}: expected HH:MM")
    t = int(m.group(1)) * 60 + int(m.group(2))
    return t + 1440 if t < NIGHT_START else t


def _clock(minute):
    t = minute % 1440
    return f"{t // 60:02d}:{t % 60:02d}"


def _validate_steps(steps, name):
    if (not isinstance(steps, list) or len(steps) < 2 or steps[0].get("at") != "dusk"
            or steps[-1] != {"at": "dawn", "level": 0}):
        raise ValueError(f"{name}: a programme runs from a 'dusk' step to a final {{'at': 'dawn', 'level': 0}}")
    times = [_minute(s["at"]) for s in steps[1:-1]]
    if times != sorted(set(times)):
        raise ValueError(f"{name}: fixed-time steps must be in night order without repeats")
    for s in steps[:-1]:
        lv = s.get("level")
        if isinstance(lv, bool) or not isinstance(lv, (int, float)) or not 0 < lv <= 100:
            raise ValueError(f"{name}: step {s.get('at')!r} level must be above 0 and at most 100 %")


def level_at(steps, minute):
    """A programme's level at a minute since noon, between dusk and dawn."""
    level = steps[0]["level"]
    for s in steps[1:-1]:
        if _minute(s["at"]) <= minute:
            level = s["level"]
    return level


def night_profile(steps):
    """The programme's level at every minute from noon to noon (dusk level before the first fixed step)."""
    out, level = [], steps[0]["level"]
    changes = [(_minute(s["at"]), s["level"]) for s in steps[1:-1]]
    i = 0
    for t in range(NIGHT_START, NIGHT_START + 1440):
        while i < len(changes) and changes[i][0] <= t:
            level = changes[i][1]
            i += 1
        out.append(level)
    return out


def first_darker_minute(candidate, reference):
    """The first minute since noon at which `candidate` is darker than `reference`, or None."""
    for t, (a, b) in enumerate(zip(night_profile(candidate), night_profile(reference))):
        if a < b:
            return NIGHT_START + t
    return None


def never_darker(adapted, original):
    """True if `adapted` is at least as bright as `original` at every minute of the night."""
    return first_darker_minute(adapted, original) is None


def check_program(steps, caps):
    """Where a programme exceeds a controller's declared capabilities.
    Each issue says whether a brighter-only adaptation can resolve it."""
    issues = []
    fixed = steps[1:-1]
    if len(steps) - 1 > caps["max_steps_per_program"]:
        issues.append({"issue": "steps", "adaptable": True,
                       "detail": f"{len(steps) - 1} steps; the controller holds {caps['max_steps_per_program']}"})
    off_grid = [s["at"] for s in fixed if _minute(s["at"]) % caps["time_resolution_min"]]
    if off_grid:
        issues.append({"issue": "time_resolution", "adaptable": True,
                       "detail": f"{', '.join(off_grid)} not on the controller's {caps['time_resolution_min']}-minute grid"})
    levels = [s["level"] for s in steps[:-1]]
    if any(lv > caps["max_level_pct"] for lv in levels):
        issues.append({"issue": "max_level", "adaptable": False,
                       "detail": f"asks for {max(levels)} %; the controller reaches {caps['max_level_pct']} %"})
    low = [lv for lv in levels if lv < caps["min_level_pct"]]
    if low:
        issues.append({"issue": "min_level", "adaptable": True,
                       "detail": f"{min(low)} % is below the controller's stable minimum {caps['min_level_pct']} %"})
    coarse = [lv for lv in levels if lv % caps["level_step_pct"]]
    if coarse:
        issues.append({"issue": "level_step", "adaptable": True,
                       "detail": f"levels {', '.join(map(str, sorted(set(coarse))))} are not multiples of {caps['level_step_pct']} %"})
    return issues


def _supported_level(level, caps):
    """The lowest level the driver holds that is not below `level`."""
    step = caps["level_step_pct"]
    return math.ceil(max(level, caps["min_level_pct"]) / step - 1e-9) * step


def adapt_program(steps, caps):
    """The cheapest programme this controller can run that is never darker than `steps`."""
    res = caps["time_resolution_min"]
    # 1. On the controller's time grid, each cell takes the brightest level the original reaches inside it.
    fixed = [(_minute(s["at"]), s["level"]) for s in steps[1:-1]]
    out = [{"at": "dusk", "level": steps[0]["level"]}]
    for start in range(NIGHT_START, NIGHT_START + 1440, res):
        inside = [lv for t, lv in fixed if start < t < start + res]
        level = max([level_at(steps, start)] + inside)
        if level != out[-1]["level"]:
            out.append({"at": _clock(start), "level": level})
    # 2. Levels rise to what the driver can hold: never below its stable minimum, rounded up to its granularity.
    for s in out:
        s["level"] = _supported_level(s["level"], caps)
    out = [s for i, s in enumerate(out) if i == 0 or s["level"] != out[i - 1]["level"]]
    # 3. Too many steps: merge the neighbouring pair whose merge adds the least light (the brighter level wins).
    while len(out) > caps["max_steps_per_program"]:
        def span(i):
            begin = NOMINAL_DUSK if i == 0 else _minute(out[i]["at"])
            end = _minute(out[i + 1]["at"]) if i + 1 < len(out) else NOMINAL_DAWN
            return max(1, end - begin)

        def cost(i):
            top = max(out[i]["level"], out[i + 1]["level"])
            return (top - out[i]["level"]) * span(i) + (top - out[i + 1]["level"]) * span(i + 1)

        i = min(range(len(out) - 1), key=lambda j: (cost(j), j))
        out[i] = {"at": out[i]["at"], "level": max(out[i]["level"], out[i + 1]["level"])}
        del out[i + 1]
        out = [s for k, s in enumerate(out) if k == 0 or s["level"] != out[k - 1]["level"]]
    out.append({"at": "dawn", "level": 0})
    return out


def adapt_programs(programs, caps):
    """Check every programme against a controller; adapt what can be adapted
    brighter-only. Returns (programs, report); report["compatible"] is False
    when an issue cannot be adapted."""
    caps = read_capabilities(caps)
    report = {"controller": caps["name"], "source": caps["source"], "verified": caps["verified"],
              "programs": {}, "blocking": []}
    if len(programs) > caps["max_programs"]:
        report["blocking"].append(f"{len(programs)} programmes; the controller/CMS holds {caps['max_programs']}")
    adapted = {}
    for name, prog in programs.items():
        _validate_steps(prog["steps"], name)
        issues = check_program(prog["steps"], caps)
        entry = {"issues": issues, "adapted": False}
        new = dict(prog)
        if any(not i["adaptable"] for i in issues):
            report["blocking"].extend(f"{name}: {i['detail']}" for i in issues if not i["adaptable"])
        elif issues:
            new_steps = adapt_program(prog["steps"], caps)
            if not never_darker(new_steps, prog["steps"]) or check_program(new_steps, caps):
                raise AssertionError(f"{name}: adaptation failed its own guarantee")       # a bug, never a user error
            new = dict(prog, steps=new_steps, original_steps=prog["steps"])
            entry["adapted"] = True
            window = slice(NOMINAL_DUSK - NIGHT_START, NOMINAL_DAWN - NIGHT_START)
            entry["added_full_output_hours_per_night"] = round(
                sum(a - b for a, b in zip(night_profile(new_steps)[window], night_profile(prog["steps"])[window])) / 6000, 3)
        adapted[name] = new
        report["programs"][name] = entry
    if "photocell" not in caps["dusk_dawn"] and "astronomical" not in caps["dusk_dawn"]:
        report["blocking"].append("the controller has no dusk/dawn source")
    report["compatible"] = not report["blocking"]
    return adapted, report


# ------------------------------------------------------------------- readiness
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def readiness_record(directory, files, compatibility=None):
    """A fresh record for the files in `directory`, every gate pending."""
    directory = Path(directory)
    return {"schema": READINESS_SCHEMA,
            "note": "Nothing in this directory is approved for import until `nocturne readiness` passes on this record. "
                    "Fill each gate's approved_by, role, date (YYYY-MM-DD) and evidence (a document or ticket reference), "
                    "and set status to approved, or to not_applicable with the reason as evidence. Do not edit the files "
                    "below after approval: their hashes are checked.",
            "files": {name: sha256_file(directory / name) for name in sorted(files)},
            "compatibility": compatibility or {"checked": False,
                                               "detail": "no controller capability profile: rerun `nocturne schedule --controller`"},
            "gates": [{"id": gid, "title": title, "question": question, "status": "pending",
                       "approved_by": "", "role": "", "date": "", "evidence": ""} for gid, title, question in GATES]}


def evaluate_readiness(record_path):
    """READY only if the files are unchanged, the programmes fit a declared
    controller, and every gate is approved (or not applicable) with a named
    person, role, date and evidence reference."""
    path = Path(record_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("schema") != READINESS_SCHEMA:
        raise ValueError(f"{record_path}: not a readiness record ({READINESS_SCHEMA})")
    blockers, passed = [], []
    for name, digest in sorted(record.get("files", {}).items()):
        target = path.parent / name
        if not target.exists():
            blockers.append(f"file {name}: missing")
        elif sha256_file(target) != digest:
            blockers.append(f"file {name}: changed after this record was made; approvals no longer apply to it")
        else:
            passed.append(f"file {name}: unchanged")
    if not record.get("files"):
        blockers.append("the record lists no files")
    compat = record.get("compatibility", {})
    if not compat.get("checked"):
        blockers.append("compatibility: " + compat.get("detail", "not checked against a controller profile"))
    elif not compat.get("compatible"):
        blockers.append("compatibility: " + "; ".join(compat.get("blocking", [])))
    else:
        passed.append(f"compatibility: fits {compat.get('controller')}"
                      + ("" if compat.get("verified") else " (profile declared, not yet bench-verified: see the equipment gate)"))
    seen = {g.get("id") for g in record.get("gates", []) if isinstance(g, dict)}
    for gid, title, _ in GATES:
        if gid not in seen:
            blockers.append(f"{title}: gate missing from the record")
    for g in record.get("gates", []):
        title = g.get("title", g.get("id", "gate"))
        status = g.get("status")
        if status not in GATE_STATUSES:
            blockers.append(f"{title}: status must be one of {', '.join(GATE_STATUSES)}")
            continue
        if status == "pending":
            blockers.append(f"{title}: pending — {g.get('question', '')}")
            continue
        missing = [k for k in ("approved_by", "role", "date", "evidence")
                   if not isinstance(g.get(k), str) or not g.get(k).strip()]
        if missing:
            blockers.append(f"{title}: {status} but missing {', '.join(missing)}")
            continue
        try:
            when = date.fromisoformat(g["date"].strip())
        except ValueError:
            blockers.append(f"{title}: date {g['date']!r} is not YYYY-MM-DD")
            continue
        if when > date.today():
            blockers.append(f"{title}: dated in the future ({when.isoformat()})")
            continue
        passed.append(f"{title}: {status} by {g['approved_by']} ({g['role']}), {when.isoformat()}, evidence {g['evidence']}")
    return {"ready": not blockers, "blockers": blockers, "passed": passed}


# -------------------------------------------------------------------- reconcile
def reconcile(programs, assignments, readback_programs, readback_assignments):
    """Compare what the CMS reports with what was intended.

    `programs` / `readback_programs`: {name: [steps]}; `assignments`:
    [(segment, intended programme)]; `readback_assignments`: {segment: programme
    the CMS holds}. A segment the CMS does not report, a programme it does not
    hold, or any minute darker than intended is an error; brighter is a warning
    (light kept, saving lost)."""
    errors, warnings, ok = [], [], 0
    intended_segments = set()
    darker_at = {}                                # (held, intended) -> first darker minute, computed once per pair
    for segment, intended in assignments:
        intended_segments.add(segment)
        held = readback_assignments.get(segment)
        if held is None:
            errors.append(f"{segment}: not in the CMS readback (not loaded, or not reported)")
            continue
        if held not in readback_programs:
            errors.append(f"{segment}: the CMS assigns {held!r}, which its programme readback does not contain")
            continue
        if intended not in programs:
            errors.append(f"{segment}: intended programme {intended!r} is not in the exported programmes")
            continue
        want, have = programs[intended], readback_programs[held]
        if (held, intended) not in darker_at:
            darker_at[held, intended] = first_darker_minute(have, want)
        t = darker_at[held, intended]
        if t is not None:
            errors.append(f"{segment}: {held!r} is darker than intended {intended!r} from {_clock(t)} "
                          f"({level_at(have, t)} % instead of {level_at(want, t)} %)")
            continue
        if held != intended:
            warnings.append(f"{segment}: holds {held!r} instead of {intended!r} (never darker; confirm the mapping, "
                            "e.g. a High-Injury Network segment)")
        elif have != want:
            warnings.append(f"{segment}: {held!r} is brighter than intended at some hours (safe; saving reduced)")
        ok += 1
    extra = sorted(set(readback_assignments) - intended_segments)
    if extra:
        warnings.append(f"{len(extra)} segment(s) in the readback are not in this wave, e.g. {', '.join(extra[:5])}")
    return {"matched": ok, "errors": errors, "warnings": warnings, "ok": not errors}


def read_readback_assignments(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in ("segment", "program") if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: needs the columns segment,program (missing {', '.join(missing)})")
        out = {}
        for n, row in enumerate(reader, start=2):
            seg, prog = (row["segment"] or "").strip(), (row["program"] or "").strip()
            if not seg or not prog:
                raise ValueError(f"{path}, row {n}: segment and program are required")
            if seg in out and out[seg] != prog:
                raise ValueError(f"{path}, row {n}: segment {seg} is listed with two programmes")
            out[seg] = prog
    return out


def read_programs(path):
    """{name: steps} from a programs.json (or a CMS readback in the same shape)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    progs = doc.get("programs", doc) if isinstance(doc, dict) else None
    if not isinstance(progs, dict) or not progs:
        raise ValueError(f"{path}: expected {{'programs': {{name: {{'steps': [...]}}}}}}")
    out = {}
    for name, prog in progs.items():
        steps = prog.get("steps") if isinstance(prog, dict) else prog
        _validate_steps(steps, f"{path}: {name}")
        out[name] = steps
    return out
