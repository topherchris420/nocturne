# Nocturne

**Light where it is needed. Darkness where it is not.**

Nocturne is an open-source toolkit for planning a darker city—and testing whether the plan worked. Set a sky-brightness target, compare changes across buildings, signs, sports fields and streetlights, and find the least-cost combination that meets the target under the conditions you specify.

A lit crossing does not need an illuminated sky. An occupied office does not need a glowing facade. Nocturne treats useful lighting and unwanted spill as separate things to account for: keep the service people need, then work backward from the night you want to restore.

Built by **Christopher Woodyard / Vers3Dynamics**, with Washington, DC as the worked example.

> **Research prototype · Python 3.10+ · MIT license.** The planner, simulations, reports and trial-analysis tools run today. City integration, physical controllers and field validation remain deployment work. DC results are model estimates; the restoration demonstration uses entirely invented data.

[Quick start](#quick-start) · [Restoration example](#a-complete-restoration-example) · [DC estimates](#washington-dc-the-worked-example) · [Documentation](#documentation)

## What you can do

| Start with a question | Use Nocturne to… |
|---|---|
| Which changes would reach our darkness target? | Choose a portfolio across named owners, observation points and weather scenarios, within a budget and declared service constraints. |
| What if the target cannot be reached? | Identify a budget shortfall or show that the available actions are insufficient. |
| Which sources contribute to the glow? | Design randomized source-isolation trials and analyze paired target/control observations. |
| Could existing streetlights use less energy? | Compare a year of electricity, cost and emissions under scheduled and adaptive lighting. |
| What happens during a network outage? | Simulate a lamp continuing to follow local rules after losing its connection. |
| Where does a fixture send its light? | Inspect IES photometry files for backlight, uplight and glare, and estimate light at a window. |
| How could a city coordinate a trial? | Export streetlight schedules, create a phased rollout, check crash data, and publish a shared Night Signal calendar. |

## Explore without installing

Download the repository through **Code → Download ZIP**, extract it, and open one of these files in your browser:

| File | What to explore |
|---|---|
| [Restoration report](examples/restoration/report.html) | An offline brief showing the selected interventions, costs and remaining sky brightness in the synthetic district. |
| [Decision brief](docs/brief.html) | Interactive estimates of energy costs, lighting through the night, modeled skies and the proposed rollout. |
| [Operator console](console/index.html) | A standalone browser demonstration of streetlight controller behavior. |

GitHub displays HTML source at these links. Open the downloaded files locally to see the interfaces. These demonstrations do not connect to live lights.

## Quick start

You need **Python 3.10 or newer**. Git is optional if you download and extract the ZIP instead.

```bash
git clone https://github.com/topherchris420/nocturne.git
cd nocturne
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The Windows setup does not require script activation. In subsequent commands, replace `nocturne` with `.\.venv\Scripts\nocturne.exe`, and `python` with `.\.venv\Scripts\python.exe`.

The `dev` extra includes tests and chart generation. For the core command-line tools alone, install with `python -m pip install -e .`.

Run the included restoration example:

```bash
nocturne restore examples/restoration/district.json --report my-restoration.html
```

Open `my-restoration.html` in your browser. Choose a new filename each time; the report writer refuses to overwrite an existing file.

Then compare annual energy use or watch a simulated lamp lose its connection:

```bash
nocturne business-case
nocturne trace --road local --offline-at 22:15
```

Run these commands from the project folder so the included data and examples are available. If `nocturne` is not found, reactivate the environment or use its executable path. Use `nocturne --help` or `nocturne restore --help` for command options.

## A complete restoration example

The included district contains **seven source groups, three observation points and two weather scenarios**. Under an $8,000 budget, the planner selects this $6,550 package:

| Source | Selected change | Invented cost |
|---|---|---:|
| Facades | Switch decorative uplights off after closing | $500 |
| Offices | Close blinds and zone vacant rooms while retaining occupied task lighting | $2,200 |
| Signs | Apply a shared curfew to nonessential signs | $250 |
| Sports fields | Connect operation to bookings and shutdown checks | $1,200 |
| Residential streets | Combine shielding with a reviewed schedule | $2,400 |
| **Total** | **All six modeled place-and-weather targets met** | **$6,550** |

**Every cost, contribution, owner, permission and review flag in this example is synthetic.** It demonstrates the software, not a DC forecast or an approved lighting design. The crossing remains unchanged. A monument owner's unapproved curfew is excluded, while that monument's light still counts toward the pollution budget.

### Make failure visible

Try a budget that cannot buy the required changes:

```bash
nocturne restore examples/restoration/district.json --budget 1000
```

This deliberately returns **exit code 3** and reports the shortfall. The planner distinguishes three outcomes:

| Outcome | Meaning |
|---|---|
| `feasible` | The least-cost eligible portfolio meets every supplied target within budget. |
| `budget_shortfall` | A qualifying portfolio exists, but the budget cannot cover it. |
| `outside_available_actions` | No eligible combination reaches all targets, even with an unlimited budget. |

These results are conditional on the supplied model. The exact search supports grouped district projects and stops above **1,000,000 candidate portfolios**. It is not a city-scale optimizer for individual lamps.

### Connect the plan to measurements

Analyze the included synthetic observations:

```bash
nocturne attribute examples/restoration/trial.json examples/restoration/synthetic-readings.csv
```

The demonstration recovers source contributions of approximately **0.817 and 0.557 mcd/m²**, against injected values of **0.800 and 0.550**. This is a software recovery check using invented observations; it does not validate the district model or establish field effectiveness.

To prepare a new study design:

```bash
nocturne experiment --source facades --source signs --start 2027-01-04 --seed "publish-before-measuring" --pairs 12 --fraction 0.5 --out my-trial
```

This creates `my-trial/trial.json` and an empty `my-trial/readings.csv`. It schedules separate source groups on separate nights, with independently randomized baseline/dimmed window order. It does not operate any lights. Twelve nights per source is an example, not a power calculation.

A field study needs consenting owners, reviewed lighting levels, calibrated target and control stations, preregistered quality rules, and records of the delivered light output. After collecting and screening observations:

```bash
nocturne attribute my-trial/trial.json my-trial/readings.csv
```

The analysis compares paired observations in linear luminance, reports exclusions and missing data, and adjusts inference across sources. Measurements can inform revised planning inputs; they do not automatically authorize a lighting change.

**[Read the full restoration protocol](docs/RESTORATION.md)** for input units, solver guarantees, study assumptions and the field procedure. To regenerate all synthetic example artifacts in a new directory:

```bash
python tools/restoration_demo.py --out my-restoration-demo
```

## Washington, DC: the worked example

Nocturne includes aggregates from a **DDOT inventory retrieved October 14, 2026**: 72,512 active lights, with 72,068 included as dimmable in the annual comparison. This is a stored snapshot. [Data source and processing notes →](data/dc/README.md)

The default 2027 model estimates:

| Lighting plan | Annual electricity | Annual electricity saving |
|---|---:|---:|
| Baseline: commissioned maximum output all night | 16.4 million kWh | — |
| Scheduled dimming on existing compatible equipment | 11.5 million kWh | About $641,000 |
| Adaptive control responding to activity | 10.9 million kWh | About $720,000 |
| Adaptive control, shielding and warmer replacement lights | 11.5 million kWh | About $645,000 |

Dollar savings assume **$0.13/kWh**, exclude implementation costs, and compare against an all-night static baseline. Existing overnight dimming would reduce the additional savings. Warmer lights require more electricity for the same useful light in this model, which explains the final row's tradeoff. These are estimates, not measured savings.

Change the price assumption yourself:

```bash
nocturne business-case --price 0.18
```

The first rollout step, **Phase 0**, prepares schedules for existing compatible controllers. The default minimum is 50% on streets without presence sensing, retaining higher applicable floors. Separate High-Injury Network programs never drop below 60%; the city must identify and assign those streets. Exported files need translation into the actual municipal management system.

### One clock for the night

Streetlights are one contributor to skyglow—the bright haze above a city. Buildings, signs, sports fields and other sources need their own owners and actions.

**Night Signal** proposes a shared schedule that those owners could follow, exported as JSON and an iCalendar feed. Its modeled benefits depend on participation. It is a protocol proposal, not an adopted city policy or an operating public service. The migration flag is supplied by the caller; the CLI does not fetch a live forecast.

The separate DC sky model borrows a streetlight-share assumption from Tucson. DC measurements are needed to establish the local share. Modeled star counts are illustrations, not promises.

## More things to try

**Estimate sky brightness at six DC locations:**

```bash
nocturne sky
```

**Inspect an included synthetic fixture and estimate light reaching a window:**

```bash
nocturne bug examples/ies/synthetic-globe-4000lm-ulr15.ies
nocturne trespass examples/ies/synthetic-globe-4000lm-ulr15.ies --height 9 --setback 10 --window 5
```

“BUG” means backlight, uplight and glare. Distances above are in metres.

**Create a phased trial and export its first wave of schedules:**

```bash
nocturne pilot --seed "publish-before-drawing" --out plan.csv
nocturne schedule --plan plan.csv --wave 1 --out phase0
```

This writes `plan.csv`, `phase0/programs.json` and an assignment CSV. Publish the seed before drawing groups for a real trial. The `brake` command analyzes supplied crash records before subsequent waves; see `nocturne brake --help` and the [playbook](docs/PLAYBOOK.md).

**Create a 30-night Night Signal calendar:**

```bash
nocturne signal --date 2026-10-14 --ics curfew.ics --days 30
```

This writes `curfew.ics` and prints the first night's schedule as JSON. Signing requires the optional `--key` setting; the default output is unsigned.

**Run the network night simulation with charts:**

```bash
nocturne simulate --out simulation-output
```

Allow several minutes. The `dev` or `charts` extra supplies the chart dependency. The [recorded simulation report](out/report.md) uses a representative October night scaled to 75,000 lights; it is a different experiment from the DC inventory's annual comparison above.

**Try another location's clock:**

```bash
nocturne trace --site sydney --road local --start "2027-01-15 20:00" --end "2027-01-16 08:00"
```

There are 17 location presets. Changing the clock and geography does not supply another city's inventory; the included fleet and sky maps remain DC-specific.

## How the controller fits in

The **VDL-7 reference controller** models how an individual lamp chooses brightness from time, road type, activity, weather and emergency instructions. It keeps schedules locally, so losing the network does not erase the lighting program. If the clock also becomes unreliable, a fallback uses a light sensor and previously learned night timing.

The planning tools operate around that model: estimate annual effects, export schedules, organize trials and analyze observations. The restoration planner extends the decision beyond streetlights to multiple owners and source types. None of these commands actuates physical infrastructure.

## What still needs field work

- **Engineering and integration.** Python controller behavior needs hardware implementation, municipal integration and field testing. Declared service fractions and review flags do not establish photometric safety.
- **Local evidence.** Source contributions, intervention effects, costs, owner permissions, traffic and existing schedules need verification. Some inventory wattages are imputed from comparable fixtures.
- **Model coverage.** Restoration targets hold only across supplied scenarios. The DC sky model simplifies atmospheric transport and omits terrain and buildings.
- **Safety monitoring.** The crash-data brake can flag concerning observations; a “continue” result does not prove safety.
- **Economics and participation.** New adaptive controllers do not pay for themselves through energy savings alone at ordinary hardware costs in this model. Multi-owner gains require actual participation.

A practical starting point is **one willing building owner, one avoidable spill source and two calibrated observation points**. Establish that useful lighting survives while unwanted light falls, then use the evidence to revise the next plan.

## Documentation

| Resource | Contents |
|---|---|
| [Restoration workflow](docs/RESTORATION.md) | Project schema, units, optimization guarantees, trial design and measurement analysis. |
| [Synthetic example](examples/restoration/README.md) | Inputs, provenance, generated results and reproduction instructions. |
| [DC playbook](docs/PLAYBOOK.md) | Rollout, costs, measurement plan and governance. |
| [Evidence review](docs/EVIDENCE.md) | Supporting research, contrary findings and limitations. |
| [Technology proposal](docs/TECHNOLOGY.md) | Lighting controls, optics, spectrum, sensors and measurement options, with costs and readiness. |
| [Engineering reference](docs/ENGINEERING.md) | Controller behavior, specification corrections, security and simulation details. |
| [DC inventory notes](data/dc/README.md) | Data source, aggregation and fixture classification. |
| [Controller](vdl7/controller.py) · [CLI](vdl7/cli.py) · [Tests](tests/) | Implementation and verification. |

To run the existing tests after installing the `dev` extra:

```bash
python -m pytest -q
```

The browser/Python parity test also requires Node.js and is skipped when it is unavailable.

Nocturne began as the reference implementation for **VD-DSL-SPEC-001 RevA, DC Dark-Sky Lighting Engineering Specification** (Christopher Woodyard, Vers3Dynamics, October 2026). The engineering reference preserves that specification-level detail.

## License

[MIT](LICENSE).
