# One-building field pilot starter

This folder contains **templates, not field data**. There is no approved property, executed trial, calibrated meter reading or measured skyglow reduction in this repository.

1. Read [the complete field protocol](../../docs/FIELD_PILOT.md) before approaching an owner or changing a switch.
2. Create a new study with `nocturne experiment` and a public fixed seed. The output includes `trial.json` and the *correct* `readings.csv` template; do not reuse this folder's notes CSV for analysis.
3. Copy `readiness.json` to your **private working directory**, fill `site_id`, `source`, `trial_sha256` and evidence references for all six checks.
4. Run `nocturne field-check readiness.json trial.json`. Pending checks refuse readiness, and even a passing manifest remains a **self-reported** declaration, not verified permission.
5. Preserve instrument logs and safety exception records. Use `nocturne attribute` only after screening the completed experiment.

Do not commit addresses, photos of residents, personal contact information or private signed permission documents without authorization.
