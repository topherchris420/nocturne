"""Preregistered source-isolation trials, with one randomized crossover per night.

The independent unit is a night, never a sensor reading. This estimates a
source's response at one receptor; it does not reconstruct an entire city.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import random
import statistics
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .restore import fields, number, text
from .skyglow import cd_from_msas

COLUMNS = ["pair_id", "period", "status", "reason", "samples", "applied_fraction", "target_msas", "control_msas"]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def make_trial(sources, start, seed, pairs=12, dim_fraction=0.5, tz="America/New_York", control_scale=1.0, synthetic=False):
    """Independent pseudorandom AB/BA assignments, reproducible from a public seed.

    Source groups occupy separate nights; all other groups retain baseline.
    These are reviewable study windows, not executable controller schedules.
    """
    text(seed, "seed")
    if type(synthetic) is not bool:
        raise ValueError("synthetic must be true or false")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 10:
        raise ValueError("supply 1–10 source IDs")
    if any(not isinstance(s, str) or not s or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in s) for s in sources):
        raise ValueError("source IDs may contain only letters, digits, hyphens and underscores")
    if len(set(sources)) != len(sources):
        raise ValueError("source IDs must be unique")
    if type(pairs) is not int or not 6 <= pairs <= 64:
        raise ValueError("pairs must be an integer from 6 to 64 per source")
    number(dim_fraction, "dim_fraction", high=0.95)
    number(control_scale, "control_scale", high=100)
    try:
        first = date.fromisoformat(start)
        zone = ZoneInfo(tz)
        first + timedelta(days=len(sources) * pairs)  # validate the full date range
    except (ValueError, TypeError, OverflowError, ZoneInfoNotFoundError) as exc:
        raise ValueError("use an ISO start date with room for the full trial and a valid IANA timezone; install tzdata if needed") from exc
    out = {"schema_version": 1, "synthetic": synthetic, "sources": sorted(sources), "start": start, "seed": seed,
           "pairs": pairs, "dim_fraction": dim_fraction, "timezone": tz, "control_scale": control_scale,
           "assignments": []}
    for i, source in enumerate(out["sources"]):
        for j in range(pairs):
            night = first + timedelta(days=i * pairs + j)
            pair = f"{source}-{night.isoformat()}"
            # Each pair uses an independent hash bit. Do not force alternation or
            # rebalance after seeing weather/results: the sign-flip test assumes this.
            order = int(digest([seed, pair])[-1], 16) % 2
            for period in (1, 2):
                day = night if period == 1 else night + timedelta(days=1)
                at = datetime.combine(day, time(23, 20) if period == 1 else time(0, 20), zone)
                treatment = (period == 2) if order == 0 else (period == 1)
                out["assignments"].append({"pair_id": pair, "source": source, "night": night.isoformat(),
                    "period": period, "condition": "dim" if treatment else "baseline",
                    "requested_fraction": dim_fraction if treatment else 1.0,
                    "start_utc": at.astimezone(timezone.utc).isoformat(),
                    "end_utc": (at + timedelta(minutes=20)).astimezone(timezone.utc).isoformat()})
    out["trial_sha256"] = digest(out)
    return out


def validate_trial(trial):
    fields(trial, "schema_version synthetic sources start seed pairs dim_fraction timezone control_scale assignments trial_sha256", "trial")
    if type(trial["schema_version"]) is not int or trial["schema_version"] != 1:
        raise ValueError("trial schema_version must be 1")
    if digest({k: v for k, v in trial.items() if k != "trial_sha256"}) != trial["trial_sha256"]:
        raise ValueError("trial fingerprint does not match its contents")
    expected = make_trial(trial["sources"], trial["start"], trial["seed"], trial["pairs"],
                          trial["dim_fraction"], trial["timezone"], trial["control_scale"], trial["synthetic"])
    if trial != expected:
        raise ValueError("trial does not match its reproducible design/hash; use the original preregistration")


def write_template(trial, path):
    validate_trial(trial)
    with open(path, "x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for a in trial["assignments"]:
            writer.writerow({"pair_id": a["pair_id"], "period": a["period"]})


def _percentile(values, p):
    x = (len(values) - 1) * p
    lo, hi = math.floor(x), math.ceil(x)
    return values[lo] + (values[hi] - values[lo]) * (x - lo)


def _sign_p(values, seed):
    observed = abs(sum(values))
    if len(values) <= 16:
        trials = itertools.product((-1, 1), repeat=len(values))
        extreme = sum(abs(sum(s * v for s, v in zip(signs, values))) >= observed - 1e-12 for signs in trials)
        return extreme / (2 ** len(values)), "exact paired randomization"
    rng = random.Random(seed)
    extreme = sum(abs(sum(rng.choice((-1, 1)) * v for v in values)) >= observed - 1e-12 for _ in range(9999))
    return (extreme + 1) / 10000, "Monte Carlo paired randomization (9,999 draws)"


def analyze(trial, path):
    """Analyze complete pairs, retaining negative effects and every exclusion.

    Rows must contain externally quality-screened window means expressed as
    MSAS, calculated by averaging *linear luminance* first. The control's
    additive response is scaled by a preregistered coefficient. Intervals are
    exploratory percentile bootstraps; p values use the randomized assignment.
    """
    validate_trial(trial)
    expected = {(a["pair_id"], str(a["period"])): a for a in trial["assignments"]}
    rows = {}
    with open(path, encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != COLUMNS:
            raise ValueError("readings CSV header must be: " + ",".join(COLUMNS))
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"row {line}: incorrect number of CSV fields")
            key = (row["pair_id"], row["period"])
            if key not in expected or key in rows:
                raise ValueError(f"row {line}: unknown or duplicate pair/period")
            if row["status"] not in ("ok", "excluded"):
                raise ValueError(f"row {line}: status must be ok or excluded, never silently dropped")
            if row["status"] == "excluded":
                text(row["reason"], f"row {line} exclusion reason")
                rows[key] = row
                continue
            try:
                samples = int(row["samples"])
                if samples < 5:
                    raise ValueError("at least 5 samples per window required")
                for field, lo, hi in (("target_msas", 10, 25), ("control_msas", 10, 25), ("applied_fraction", 0, 1)):
                    row[field] = number(float(row[field]), field, lo, hi)
            except ValueError as exc:
                raise ValueError(f"row {line}: {exc}") from exc
            if abs(row["applied_fraction"] - expected[key]["requested_fraction"]) > 0.01 + 1e-12:
                raise ValueError(f"row {line}: delivered level differs from assignment; mark the window excluded and explain")
            rows[key] = row
    effects = {source: [] for source in trial["sources"]}
    lost = []
    pairs = sorted({a["pair_id"] for a in trial["assignments"]})
    for pair in pairs:
        keys = [(pair, "1"), (pair, "2")]
        if any(key not in rows for key in keys):
            lost.append({"pair_id": pair, "reason": "missing period", "details": [str(k[1]) for k in keys if k not in rows]})
            continue
        if any(rows[k]["status"] == "excluded" for k in keys):
            lost.append({"pair_id": pair, "reason": "excluded period", "details": [rows[k]["reason"] for k in keys if rows[k]["status"] == "excluded"]})
            continue
        base = next(k for k in keys if expected[k]["condition"] == "baseline")
        dim = next(k for k in keys if expected[k]["condition"] == "dim")
        delta = lambda field: 1000 * (cd_from_msas(rows[base][field]) - cd_from_msas(rows[dim][field]))
        effects[expected[base]["source"]].append(delta("target_msas") - trial["control_scale"] * delta("control_msas"))
    estimates = []
    family = len(trial["sources"])
    for source, values in effects.items():
        n = len(values)
        item = {"source": source, "usable_pairs": n, "planned_pairs": trial["pairs"],
                "complete": n == trial["pairs"], "status": "insufficient_data"}
        if n >= 6:
            seed = digest([trial["trial_sha256"], source, "inference"])
            rng = random.Random(seed)
            boots = sorted(statistics.fmean(rng.choices(values, k=n)) for _ in range(10000))
            alpha = 0.05 / family
            interval = [_percentile(boots, alpha / 2), _percentile(boots, 1 - alpha / 2)]
            effect = statistics.fmean(values)
            p, method = _sign_p(values, seed)
            adjusted = min(1.0, p * family)
            status = ("reduction_detected" if effect > 0 else "unexpected_brightening") if adjusted <= 0.05 else "not_resolved"
            item.update(status=status if item["complete"] else "incomplete_exploratory", removed_mcd_m2=effect,
                        removed_interval_mcd_m2=interval, source_at_baseline_mcd_m2=effect / (1 - trial["dim_fraction"]),
                        source_interval_mcd_m2=[v / (1 - trial["dim_fraction"]) for v in interval],
                        p_two_sided=p, p_bonferroni=adjusted, test=method)
        estimates.append(item)
    return {"schema_version": 1, "synthetic": trial["synthetic"], "trial_sha256": trial["trial_sha256"],
            "readings_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "estimates": estimates,
            "lost_pairs": lost, "received_windows": len(rows), "planned_windows": len(expected),
            "limits": ["One preregistered final analysis; repeated looks invalidate the nominal error rate.",
                       "Exact randomization inference assumes independent randomized order and no carryover.",
                       "Bootstrap intervals are approximate, Bonferroni-adjusted across planned sources, and may undercover with few nights.",
                       "A control affected by the intervention biases attribution; verify it is outside the source footprint.",
                       "Source-at-baseline estimates assume sky luminance changes linearly with delivered light output.",
                       "Quality screening must verify moonless astronomical darkness, stable cloud/aerosol/surface conditions, calibrated sensors and no competing interventions.",
                       "Excluded or missing pairs can bias results; incomplete results remain exploratory.",
                       "An attribution at one receptor does not supply coefficients for other receptors or weather scenarios."]}
