# Work backward from a darker sky

Nocturne can now answer a more useful question than “How much can we dim?”:

**What is the least-cost set of changes that reaches a specified sky-brightness target at every protected place, without sacrificing the declared lighting service?**

This is an executable planning and measurement loop. It combines source-specific interventions, owner participation, uncertainty scenarios, and randomized field-study designs. It does not control physical infrastructure or establish that a lighting design is safe.

## The inventive move: separate the task from the spill

A bright desk does not require a bright window. A visible crossing does not require an illuminated canopy above it. A useful sports field does not require floodlights after everyone has left. The decision variable is the **complete service-preserving intervention**, which can include blinds, aiming, shielding, operating hours, booking integration, and dimming together.

A plan should not “solve” one neighborhood by leaving another above its target. Nor should a cheaper LED become permission to install more light. Nocturne therefore evaluates **absolute artificial sky-brightness budgets at named observation points**. Each target must hold in every supplied scenario. Energy efficiency alone cannot satisfy that requirement.

These ideas build on existing lighting practice; they are not claims that shielding, curfews, optimization or crossover experiments were invented here. The contribution in this repository is a runnable way to connect them to a choice of actions, accountable owners, explicit failure diagnoses, and evidence that can revise the next choice.

## Run the complete example

After the installation in the README:

```bash
nocturne restore examples/restoration/district.json
nocturne restore examples/restoration/district.json --json
nocturne restore examples/restoration/district.json --report my-restoration.html
nocturne restore examples/restoration/district.json --budget 1000
nocturne attribute examples/restoration/trial.json examples/restoration/synthetic-readings.csv
```

The $1,000 run deliberately returns exit **3**: the targets remain unmet. The report path must be new; existing files are not overwritten. Open the HTML locally in a browser. It works offline and prints without external fonts or scripts.

**Every coefficient, cost, owner, authorization, review flag and observation in this example is invented. It is not a DC forecast, quotation, consent record or measured outcome.** The existing DC inventory remains a separate dataset.

The invented district has seven source groups, three observation points, and two weather scenarios. A $6,550 portfolio meets all six constraints under an $8,000 budget:

| Source | Complete intervention | Invented cost |
|---|---|---:|
| Facades | Turn decorative uplights off after closing | $500 |
| Offices | Close blinds and zone vacant rooms; retain occupied task lighting | $2,200 |
| Signs | Apply a shared curfew to nonessential signs | $250 |
| Sports fields | Tie operation to bookings and shutdown checks | $1,200 |
| Residential streets | Combine shielding with a reviewed schedule | $2,400 |

The crossing stays unchanged. The planner excludes a deep-dimming option that violates its service floor, an office shutoff that violates its service floor, and an unconsenting monument owner's proposed curfew. Keeping an unchanged source still includes its pollution in the calculation.

Synthetic trial truth is 0.800 and 0.550 mcd/m² for the facade and sign contributions at one separate test receptor. The analyzer estimates approximately 0.817 and 0.557 mcd/m² from noisy observations. This tests recovery of known injected signals; it is **not evidence of real-world effectiveness**, and it does not calibrate the district's other places or weather scenarios.

Rebuild every example output in a new directory:

```bash
python tools/restoration_demo.py --out /tmp/nocturne-demo
```

On Windows, choose a new local output path instead of `/tmp/nocturne-demo`.

## Planner input and units

The full input is [district.json](../examples/restoration/district.json). Fields are strict: missing scenario values, duplicate IDs/JSON keys, unknown fields, NaN, infinity, out-of-range fractions and fractional cents are rejected.

| Field | Meaning |
|---|---|
| `synthetic`, `evidence` | Data origin and an explicit evidence/provenance statement |
| `budget_usd` | Capital budget; at most two decimal places |
| `receptors[].target_mcd_m2` | Maximum **artificial zenith luminance** at that location in the assessed time window; natural sky excluded |
| `sources[].owner`, `authorized` | Named owner and declared authorization for candidate changes |
| `minimum_service_fraction` | Declared minimum task-lighting service relative to that source's baseline |
| `options[].service_fraction`, `reviewed` | Declared retained service and whether the complete intervention received its required review |
| `options[].remaining_fraction` | Fraction of that source's sky contribution remaining under each named scenario; not electrical dimming percentage |
| `scenarios[].contributions_mcd_m2` | Baseline contribution from each source to **every** receptor |
| `scenarios[].unmanaged_mcd_m2` | Other artificial light not represented by an actionable source; retained in every portfolio |

All sky values use **mcd/m²**, one thousandth of a candela per square metre. They do not use lux, lumens, watts, satellite radiance, or magnitudes. Never mix those units. The source matrix must partition the artificial baseline: the unmanaged term must not also contain sources already listed. Contributions must refer to the same observation direction, spectral band, period of the night and weather case.

An option describes the **whole package for its source**. If shielding and dimming are combined, supply a single validated package; the optimizer does not add their claimed percentages. Exactly one option, or an implicit “keep”, is selected per source. Different sources must not overlap physical assets. Dependencies across sources should be represented as one jointly reviewed source/package; arbitrary cross-source dependencies are not modeled.

`service_fraction` is a screening declaration, not a calculated photometric metric. Before real use, an engineer must validate illuminance, luminance, uniformity, glare, pedestrian visibility, transitions, emergency operation and applicable local requirements, then describe that evidence in the option. An unchecked flag or an invented “60%” does not establish safety. Only the responsible owner can authorize an implementation.

## What the solver actually guarantees

For scenario $s$, receptor $r$, source $i$, and the selected complete option $a_i$, the model is:

$$
L_{sr}(a) = U_{sr} + \sum_i C_{sir} f_{sia_i}.
$$

$U$ is unmanaged artificial luminance; $C$ is the source contribution; $f$ is the remaining fraction. The planner minimizes total package cost subject to $L_{sr} \le T_r$ for **every** scenario and receptor, the budget, and declared service/authorization constraints. The fraction for a source/scenario is shared across its receptors. If an optical change redistributes light differently by direction, use a conservative fraction that bounds the residual at every receptor, or extend the model to receptor-specific effects before relying on it. The current schema accepts only packages whose source contribution does not increase in any modeled case.

The implementation prunes dominated options and enumerates the remaining portfolios. It uses integer cents for cost. It stops with an error above **1,000,000 combinations** instead of quietly returning a heuristic optimum. This is intended for a district-level set of source groups, not millions of individual lamps. Real city-scale optimization is future work.

| Result | Meaning |
|---|---|
| `feasible` | Every supplied target is met by the cheapest eligible package within budget, **conditional on the input model** |
| `budget_shortfall` | A feasible package exists; the report gives its minimum cost, even though the current budget cannot buy it |
| `outside_available_actions` | No eligible combination reaches all targets, even with an unlimited budget |

When infeasible, the selected affordable package maximizes the **least completed target** across places and scenarios. Ties favor lower summed residual luminance, then lower cost. This gives a useful partial plan while keeping the failure visible. Do not implement it as though the targets were met.

The optimistic floor removes as much light as each eligible source could possibly remove in each individual case, ignoring budget. It is a lower bound, not necessarily a jointly achievable portfolio. If that floor already exceeds a target, no amount of spending on the current action set can solve that case. A new owner, new optics, a regional agreement, or a revised target is needed. Reducing the assumed background merely to make the result pass is not a solution.

Scenarios have no probabilities. Meeting all of them is a bounded stress test, not a confidence statement and not protection against conditions absent from the input. Effects are assumed additive; interactions and changes in atmospheric transport require a better model. Target selection is a public/engineering decision, not a threshold supplied by this software.

## Find out which source matters

If every owner dims at once, you can observe a change but struggle to assign credit. Instead, test **one consenting source group at a time**, using two slow study windows within each night and independently randomized order:

```bash
nocturne experiment --source facades --source signs --start 2027-01-04 \
  --seed "publish-this-before-measuring" --pairs 12 --fraction 0.5 --out my-trial
```

PowerShell users can put this command on a single line. It creates `trial.json` and an empty `readings.csv`. It creates a **study design only**, with no connection to hardware. The package includes `tzdata` so IANA timezone conversion also works on Windows without a system timezone database.

For each source, the default design uses 12 nights, each with baseline and dimmed windows. One window starts at 23:20 local time and one at 00:20 the following date; each lasts 20 minutes. UTC timestamps preserve the actual dates and offsets. Sources occupy separate nights, so two groups are never deliberately modulated together. The design does not guarantee equal numbers of AB and BA nights: orders are independent, which is required by the implemented randomization test. It does not flicker lights or use rapid modulation.

Before collecting data:

1. Obtain owner consent and an engineering review for both levels, transitions and emergency overrides. Start with nonessential decorative sources whose functions have ended.
2. Establish an unaffected control station and a target station with stable orientation, calibration and spectral response. The control must be outside the intervention's footprint; proximity alone is insufficient.
3. Publish the exact trial JSON, seed, endpoints, quality rules, planned final analysis and any control scaling. The hash is a reproducibility fingerprint, **not a signature or proof of publication**. Do not search seeds for a desired order or change the design after seeing results.
4. Provide a settling period before each observation window, restore baseline between assignments as needed, and validate that there is no carryover. Record the actual light output and other lighting activity. The software does not perform these steps.
5. Screen windows by predeclared criteria for astronomical darkness, Moon below the horizon, clouds, aerosol, snow/surface changes, sensor health, competing interventions and delivery failures. The fixed calendar does **not** automatically find moonless nights. Publish exclusions without looking at the desired result. Twelve nights is an example, not a power calculation; use pilot noise and the desired detectable effect to choose the study length.

Each CSV row corresponds to one planned window:

| Column | Input |
|---|---|
| `pair_id`, `period` | Exact identifiers from the template |
| `status` | `ok` or `excluded`; blank is an error |
| `reason` | Required explanation for exclusions; retain contemporaneous logs |
| `samples` | At least five valid samples per accepted window, not five independent experimental units |
| `applied_fraction` | Measured delivered luminous output relative to baseline, not a guessed power fraction |
| `target_msas`, `control_msas` | Window mean luminance, converted back to mag/arcsec² after averaging in **linear** units |

Convert individual readings with `vdl7.skyglow.cd_from_msas`, average luminance, then convert with `msas_from_cd`. Do not average raw logarithmic magnitudes and treat that as average light. Sensor bandpass differences still require calibration. Keep the original readings; this CSV contains only window summaries. Existing `vdl7.observe.dark` can assist with solar and lunar screening of timestamped logs, but weather and other quality checks remain separate.

```bash
nocturne attribute my-trial/trial.json my-trial/readings.csv
```

The per-night effect is the target's baseline-minus-dim luminance difference minus the corresponding control difference multiplied by the preregistered `control_scale` (default 1). That default assumes equal **additive** nuisance variation at the two stations; it must be checked rather than assumed from equal percentage variation. Estimate a different coefficient from independent baseline observations, not the treatment data.

The analysis uses nights as the independent units, converts to linear luminance, preserves negative estimates, and reports every missing or excluded pair. Under a linear response, dividing the measured reduction by `1 - fraction` estimates the source's baseline contribution at that receptor. This assumption must be checked for actual fixtures, sky conditions and sensor response.

The two-sided randomization test swaps baseline/dim labels independently within nights. It is exact through 16 usable nights and uses 9,999 reproducible Monte Carlo draws above that, with the plus-one correction. P values are Bonferroni-adjusted over **all planned sources**, including ones with insufficient data. Approximate percentile bootstrap intervals resample nights, also adjusting for the planned number of sources. Few nights, systematic exclusions and residual dependence can make those intervals unreliable; they are not guaranteed coverage bounds. The randomization inference assumes a fixed final analysis, no carryover, and no interference through the control station. Repeat analysis until significance is not permitted by this design.

At least six usable pairs are required for an estimate. Incomplete studies are explicitly exploratory. An unresolved effect means more evidence is needed, not that the source emits no light. Unexpected brightening is retained instead of clipped to zero. `synthetic` records the declared provenance; the software cannot authenticate field observations.

## Close the loop without laundering assumptions

Use the measured source contribution to revise only the matching receptor, spectral band and conditions. A streetlight estimate at one park cannot populate every building, neighborhood and hazy-night coefficient. Retain the raw logs, exclusions, trial hash, analysis, measurement uncertainty and mapping to the changed project fields in the project's evidence record.

Then rerun `restore`, implement an owner-reviewed pilot through the existing schedule/management workflow, and use independent post-change measurements to test the predicted outcome. Keep the existing crash brake and photometric checks. A good sky measurement does not establish roadway safety. The current software leaves approval and real control with the responsible people; there is no automatic promotion from a statistical result to a lighting command.

**A practical first deployment is one willing building owner, one avoidable spill source, and two calibrated observation points.** Prove that useful indoor or ground-level service survives while unnecessary outdoor light falls. Expand from measured successes, and involve neighboring jurisdictions where the remaining light comes from beyond the city boundary.

## Sources and boundaries

- [DarkSky / IES principles](https://darksky.org/resources/guides-and-how-tos/lighting-principles/): purpose, targeting, restrained levels, controls and spectrum belong in the same decision.
- [Barentine et al. (2020), Tucson municipal dimming experiment](https://arxiv.org/abs/2005.12357): source perturbation plus measurement can constrain the streetlight contribution. Its approximately 14% estimate is specific to that experiment; this planner does not assume that fraction for another city.
- [FHWA, design criteria for adaptive roadway lighting](https://www.fhwa.dot.gov/publications/research/safety/14051/005.cfm): adaptive lighting must account for the visual task and design criteria. The scalar service gate here is not a substitute for that review.
- [SciPy's reference description of paired permutation tests](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html): independent within-pair label swaps and conservative Monte Carlo counting. No SciPy dependency is required by this implementation.

See also [EVIDENCE.md](EVIDENCE.md), [TECHNOLOGY.md](TECHNOLOGY.md) and [PLAYBOOK.md](PLAYBOOK.md). The planning model is original project code; its policy targets and field effectiveness remain to be established by actual participants and measurements.
