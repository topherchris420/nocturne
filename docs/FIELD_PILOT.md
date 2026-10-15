# First measured night: a one-building field pilot

**Objective:** move Nocturne from a documented plan and synthetic recovery check to one reproducible *physical* result. This is a protocol for a consenting property's existing, separately controlled, nonessential lighting. Nocturne does not control switches or lights. The operator may refuse or stop the study at any point.

**Never change municipal, roadway, emergency, fire/egress, security, occupied-task or federal lighting using this pilot.** Do not defeat automatic controls, open electrical enclosures, improvise fixture covers or ask observers to enter an unsafe area. Confirm personnel, cleaners and deliveries before choosing a window. Obtain the responsible owner's authorization and a tested immediate rollback. Retain the original lighting state outside the reviewed windows.

## 1. Identify a source that can actually be changed

Begin with a decorative facade circuit that normally remains on from 23:20 to 00:40, is separately switched, and has no required function during those windows. If it cannot be independently switched without compromising service, choose another source. An existing blind is useful for containment, but **is not a dimmable lamp and must not be entered as an electricity saving**. If even brief changes are unsafe or unapproved, do *observational only* work instead.

Record locally, **before collecting data**:

- An anonymous public site ID; keep exact addresses and owner contact details in the owner's private file.
- Written permission, the named on-site operator, reviewed windows and service preserved; the immediate rollback procedure and emergency contact.
- The measured baseline electrical input watts or a meter trace and the circuit's existing schedule. Do not assume installed wattage is nightly consumption.
- Photographs or a diagram of emitter direction, sensor locations and obstruction/shielding, with dates and instrument serials archived privately.
- Target sky-quality-meter location and a simultaneous, unaffected control station outside the source footprint; instrument calibration, orientation, integration cadence, synchronized clocks and instrument-specific offsets.
- Conditions and quality rules: Moon below horizon during astronomical darkness, stable clouds/aerosols, no snow transition, no adjacent lighting change, no rain on optics, no unexpected traffic headlamps contaminating a window. Log weather and exclusions even when they make the result less attractive.

The experiment measures **zenith sky brightness**, not window illuminance. Window spill may also be measured in lux with a calibrated meter, but that is a separate endpoint and **must not** be pasted into the sky-brightness fields.

## 2. Pre-register the exact first-source experiment

Install the project as in [README](../README.md#quick-start). Review the operating window with the owner, then run:

```bash
nocturne experiment --source facade --start 2027-01-04 \
  --seed "replace-with-a-public-fixed-seed" --pairs 12 --fraction 0 \
  --out my-building-trial
```

This creates `trial.json` with a SHA-256 fingerprint and a blank `readings.csv`. The generated crossover alternates two **independently randomized baseline/off periods each night**, nominally 23:20–23:40 and 00:20–00:40, one source per night. Off requires the actual circuit to support that state safely; use a tested partial fraction instead if and only if the existing hardware supports it. The independent unit is **the night**, not individual meter samples. Twelve nights is an example, **not a power calculation**.

Fix the seed, primary receptor, fixed control coefficient (default 1.0), sensor settings, weather quality screen and exclusions in a dated, immutable copy of the protocol **before any data exist**. Verify the site's source is not already off during either planned period. The randomized order must be followed by the human operator, subject to safety overrides, with actual switch/meter logs. Mark any deviations excluded with reasons; do not relabel periods after seeing the readings.

Copy [the blank readiness manifest](../examples/field-pilot/readiness.json) to a private work directory. Set `site_id`, `source` and `trial_sha256` from the generated trial; reference each signed check or calibration record without publishing personal data. Test:

```bash
nocturne field-check my-building-readiness.json my-building-trial/trial.json
```

Exit **3** means not ready; **0** means all *declared* checks are recorded and match the trial. **It is not independent verification of authorization or safe conditions.** Exit 2 indicates malformed input. The checklist never commands hardware.

## 3. Collect defensible measurements

For each randomized period, a trained observer reviews useful lighting, then the authorized operator applies the assigned state, confirms delivered output, and reverts promptly when required. Keep target and control sensors operating simultaneously with raw data and time synchronization. For every period, screen at least five instrument samples, calculate **the time average in linear luminance**, then convert to magnitudes per square arcsecond (MSAS) for the CSV. Do not average MSAS values directly. `target_msas` and `control_msas` each describe a sky-quality-meter observation, not lux, watts, or satellite radiance.

Fill the generated `readings.csv`, retaining exactly its header:

```text
pair_id,period,status,reason,samples,applied_fraction,target_msas,control_msas
```

Use `status=ok` or `status=excluded` and explain exclusions. Enter delivered `applied_fraction`, not just the commanded state. Missing observations are not zeros. Archive source logs and original sensor files locally. Do not commit identifiable site/owner information or unpublished raw measurements without permission. The [observation-notes template](../examples/field-pilot/observation-notes.csv) is a supplementary instrument/operator log, not a replacement for the analyzer's exact CSV schema.

## 4. Run the preregistered analysis

```bash
nocturne attribute my-building-trial/trial.json my-building-trial/readings.csv > analysis.json
```

The analyzer uses within-night randomized order, subtracts control-station change in **linear luminance**, reports exclusions and missing pairs, and applies a multiplicity correction when several sources were preregistered. Missing or excluded nights may bias the result. A detectable local result does **not** prove a citywide reduction, safety, a modeled DC star count, or an effect at other locations. This method also assumes negligible crossover carryover and that the control sensor is outside the intervention's light footprint.

Separately reconcile the owner's planned actions and completed switch times through `nocturne receipts`. For energy, document calibrated **input** watts and *actual baseline-on hours avoided*, including any intervening on-period; estimate `kWh = measured watts × avoided hours / 1000` only with an honest schedule counterfactual, or report unknown. Blinds receive **zero claimed kWh**. Where possible verify energy at the circuit meter rather than multiplying fixture nameplate watts.

## 5. Publish one narrow and falsifiable result

A complete report should identify the exact trial fingerprint and software commit; list planned vs valid nights; disclose exclusions, applied fractions, meter accuracy and observation-window conditions; report estimated local sky-luminance difference in **mcd/m²**, interval and adjusted p-value; present **measured energy separately from estimated energy**; and state what services were preserved.

Predeclared outcomes:

| Status | Interpretation |
|---|---|
| No owner consent / unsafe service | **Do not intervene.** No field result. |
| Check pending or sensors uncalibrated | **Not ready.** No field claim. |
| Valid measurements but incomplete trial | Exploratory, with exclusions and planned sample count disclosed. |
| Complete trial, non-resolved signal | Evidence is inconclusive at this location, not proof of no effect. |
| Complete trial, positive or negative detected change | Local effect with uncertainty and counter-explanations; **not a DC-wide claim**. |

The first success is not a stunning photograph of stars. It is a clear **measurement with an audit trail**, possibly even a null result. Publish negative findings as carefully as positive ones.

Related: [DC Tonight](TONIGHT.md), [restoration study design](RESTORATION.md), [evidence/claim levels](CLAIMS.md) and [municipal integration gates](INTEGRATION.md).
