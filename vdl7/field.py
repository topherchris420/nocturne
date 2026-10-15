"""Review a one-property field pilot before collecting sky-brightness data.

This is an evidence checklist, not authorization, certification, or a device controller.
It binds owner declarations to the exact randomized trial definition.
"""
from __future__ import annotations

import re

from .attribution import validate_trial

SCHEMA = "nocturne-field-pilot/1"
REQUIRED_CHECKS = {
    "owner_permission": "Written permission for this exact source and study window",
    "service_preservation": "Required egress, occupied work, security and access lighting reviewed",
    "rollback": "Named on-site operator and immediately reversible existing control",
    "instrument_calibration": "Calibrated target and control meters, fixed positions and units",
    "independent_control": "Control station outside the intervention footprint",
    "preregistration": "Protocol, random seed, exclusions and study endpoints frozen before observations",
}


def audit(manifest: dict, trial: dict) -> dict:
    """Evaluate declarations without interpreting them as independently verified facts."""
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValueError(f"manifest.schema: expected {SCHEMA}")
    validate_trial(trial)
    for key in ("site_id", "source", "trial_sha256"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"manifest.{key}: nonempty text required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", manifest["site_id"]):
        raise ValueError("manifest.site_id: use a non-identifying slug with letters, digits, - or _")
    if not isinstance(manifest.get("synthetic"), bool):
        raise ValueError("manifest.synthetic: use true or false")
    checks = manifest.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(REQUIRED_CHECKS):
        raise ValueError("manifest.checks: specify exactly: " + ", ".join(REQUIRED_CHECKS))
    blockers = []
    if manifest["synthetic"] or trial["synthetic"]:
        blockers.append("Synthetic/demo material cannot pass a real field readiness gate.")
    if manifest["trial_sha256"] != trial["trial_sha256"]:
        blockers.append("The manifest does not match this trial's SHA-256 fingerprint.")
    if manifest["source"] not in trial["sources"]:
        blockers.append("The named source is not among the trial's preregistered sources.")
    if len(trial["sources"]) != 1:
        blockers.append("The first-site pilot must study exactly one source; use the multi-source protocol separately.")
    passed = []
    for key, label in REQUIRED_CHECKS.items():
        check = checks[key]
        if not isinstance(check, dict):
            raise ValueError(f"manifest.checks.{key}: expected an object")
        status, evidence = check.get("status"), check.get("evidence")
        if status not in ("pending", "confirmed") or not isinstance(evidence, str):
            raise ValueError(f"manifest.checks.{key}: use status pending/confirmed and evidence text")
        if status == "confirmed" and evidence.strip():
            passed.append(label)
        else:
            blockers.append(f"{label}: pending or missing evidence reference")
    return {
        "schema": "nocturne-field-readiness/1",
        "site_id": manifest["site_id"],
        "source": manifest["source"],
        "trial_sha256": trial["trial_sha256"],
        "ready_to_collect": not blockers,
        "passed": passed,
        "blockers": blockers,
        "claim": ("Self-reported preparation only. This check neither authenticates permission nor proves "
                  "photometric safety, calibration, field performance or observed skyglow reduction. "
                  "Only the responsible people can approve or operate the existing controls."),
    }
