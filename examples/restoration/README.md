# Synthetic restoration example

**All data here are invented.** These files demonstrate software behavior, not DC measurements, real permissions, real prices or validated engineering designs.

- `district.json`: seven source groups, three observation points, two weather cases.
- `plan.json`: exact optimizer result; $6,550 of an $8,000 budget meets all six modeled targets.
- `report.html`: portable offline brief. Download/open locally; GitHub displays source.
- `trial.json`: seeded crossover design for two separate synthetic source groups at one test receptor.
- `synthetic-readings.csv`: fabricated noisy observations with a shared weather term.
- `synthetic-truth.json`: known source contributions for the recovery check.
- `attribution.json`: results from those observations, with synthetic provenance retained.

Run `python tools/restoration_demo.py --out NEW_DIRECTORY` to regenerate the files. The generator refuses to overwrite an existing directory. On the reference run, attribution recovers 0.817 and 0.557 mcd/m² against injected 0.800 and 0.550 contributions. The attribution fixture and the district matrix are separate scenarios; the fixture does not calibrate the district.

Full assumptions, units and field procedure: [RESTORATION.md](../../docs/RESTORATION.md).
