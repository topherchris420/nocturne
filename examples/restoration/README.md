# Synthetic restoration example

**All data here are invented.** These files demonstrate software behavior, not DC measurements, real permissions, real prices or validated engineering designs.

- `district.json`: seven source groups, three observation points, two weather cases.
- `plan.json`: exact optimizer result; $6,550 of an $8,000 budget meets all six modeled targets.
- `report.html`: portable offline brief. Download/open locally; GitHub displays source.
- `trial.json`: seeded crossover design for two separate synthetic source groups at one test receptor.
- `synthetic-readings.csv`: fabricated noisy observations with a shared weather term.
- `synthetic-truth.json`: known source contributions for the recovery check.
- `attribution.json`: results from those observations, with synthetic provenance retained.
- `physical-district.json`: a second invented district described physically: emitter positions, lumens, uplight and reflectance; options as physical changes; clear, hazy and snow conditions; a calibration range; and a declared rebound when signs go dark.
- `derived-district.json`: what `nocturne derive` computes from it: contributions with calibration ranges and per-place remaining fractions, plus a provenance block with the model's limits.
- `derived-plan.json`, `derived-report.html`: the plan for the derived district. $4,950 meets all nine targets at the pessimistic end of every range; on central values $4,550 would, so the uncertainty costs $400. The rebound is charged to the plan that triggers it.

Open `district.json` or `derived-district.json` in the browser planner with `nocturne app` and **New or example…**, or copy one and run `nocturne app my-copy.json` to edit and save it (Save keeps the previous version as `.bak`). Run `python tools/restoration_demo.py --out NEW_DIRECTORY` to regenerate the files. The generator refuses to overwrite an existing directory. On the reference run, attribution recovers 0.817 and 0.557 mcd/m² against injected 0.800 and 0.550 contributions. The attribution fixture and the district matrix are separate scenarios; the fixture does not calibrate the district.

Full assumptions, units and field procedure: [RESTORATION.md](../../docs/RESTORATION.md).
