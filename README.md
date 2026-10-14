# Nocturne
### Light where it is needed. Darkness where it is not.

**Nocturne is a software toolkit for exploring how cities could reduce light pollution and electricity use while keeping streets lit.** It simulates streetlights, compares lighting plans, estimates savings, and helps design a measured rollout.

Think of a residential street at 1 a.m. Instead of leaving every lamp at full brightness, a lighting system could dim them, brighten nearby lamps when someone approaches, and respond to emergencies. Each lamp could keep its own schedule even if its internet connection fails. Nocturne models that behavior—and asks what it would mean across a city.

Built by **Christopher Woodyard / Vers3Dynamics**, with Washington, DC as the worked example.

> **Current status: research prototype.** You can run the software and explore its results today. It is a Python model and planning toolkit, not certified streetlight firmware or a ready-to-deploy city service. The savings and sky improvements below are estimates, not measured outcomes from an installed Nocturne system.

[Try it](#try-it-on-your-computer) · [What it does](#what-can-you-do-with-it) · [DC example](#what-could-this-mean-for-washington-dc) · [Documentation](#go-deeper)

![Simulated streetlight brightness through the night, grouped by road type](out/night_profile.png)

*Each line shows how a type of streetlight changes brightness during the simulated night.*

## What can you do with it?

| Your question | What Nocturne provides |
|---|---|
| Could we use less electricity? | A year-long estimate of energy use, cost, and emissions under different lighting plans. |
| What happens when a connection fails? | A simulation showing how a streetlight continues operating with local rules. |
| Would the night sky get darker? | A model of sky brightness at six DC locations, with adjustable assumptions. |
| Is a fixture sending light upward or into a window? | Tools to inspect lighting measurement files and estimate light reaching a window. |
| How could a city try this gradually? | A reproducible rollout plan and a statistical check that can recommend pausing if crash data signals harm. |
| Could buildings and signs dim together too? | “Night Signal”: a proposed shared lighting schedule, exportable as data and a calendar. |

City planners can explore the costs and rollout. Lighting engineers can inspect schedules and fixture behavior. Researchers and developers can examine the models and test their assumptions.

## How it works

Nocturne has two connected parts:

- **A simulated streetlight controller.** The small computer attached to a lamp is called a *node*. Nocturne's reference controller, VDL-7, models how that node chooses brightness from the time, road type, activity, weather, and emergency instructions.
- **City planning tools.** These combine lighting rules with inventory data to estimate results, export schedules, plan a trial, and analyze measurements.

The central idea is that **each light keeps its own schedule**. A lost connection changes which new messages it receives; it does not automatically erase its dimming rules. If its clock also becomes unreliable, a fallback mode uses its light sensor and previously learned night timing, with limits described in the [engineering reference](docs/ENGINEERING.md).

Dimming follows minimum brightness rules. Emergency messages can raise output. Those modeled safeguards still need engineering review and real-world validation before deployment.

## Explore without installing Python

Download the repository using GitHub's **Code → Download ZIP**, extract it, and open either file in your browser:

- **[Decision brief](docs/brief.html)** — explore energy prices, a street through the night, modeled skies, and the rollout.
- **[Operator console](console/index.html)** — explore the controller through a standalone browser interface.

GitHub normally shows the HTML source when you click these links. Open the downloaded files locally to see the interfaces. They are demonstrations, not connections to live streetlights.

## Try it on your computer

You need **Python 3.10 or newer**. Use a terminal on macOS/Linux or PowerShell on Windows. Git is needed only for the clone command; downloading and extracting the ZIP works too.

### 1. Get the project

```bash
git clone https://github.com/topherchris420/nocturne.git
cd nocturne
```

If you used the ZIP, open your terminal in the extracted project folder instead.

### 2. Install it in a separate Python environment

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

The Windows instructions do not require activating a script. In the commands below, replace `nocturne` with `.\.venv\Scripts\nocturne.exe` on Windows.

The `dev` option includes the test and chart packages as well as Nocturne itself.

### 3. Run your first example

```bash
nocturne business-case
```

This prints a comparison of lighting plans for the included DC inventory over 2027: electricity use, estimated savings, emissions, and modeled light output. It does not change any real lights.

Try a different electricity price, in dollars per kilowatt-hour:

```bash
nocturne business-case --price 0.18
```

### 4. Watch a simulated light lose its connection

```bash
nocturne trace --road local --offline-at 22:15
```

The table shows the local time, connection mode, target brightness, and actual brightness as the night progresses. Watch the light continue using its schedule after the connection is lost.

For all commands and options:

```bash
nocturne --help
nocturne trace --help
```

**Trouble starting?** Run commands from the project folder. If `nocturne` is not found, reactivate your environment or use its full executable path. If Windows cannot find `py`, check that Python is installed and available in your terminal.

## What could this mean for Washington, DC?

The included inventory contains **72,512 active lights**, of which **72,068 are included as dimmable** in the annual comparison. These are a stored snapshot of DDOT data, not a live connection. See the [data source and processing notes](data/dc/README.md).

The documented 2027 model compares these options:

| Lighting plan | Estimated annual electricity | Estimated annual saving |
|---|---:|---:|
| Baseline: commissioned maximum output all night | 16.4 million kWh | — |
| Scheduled dimming on existing compatible equipment | 11.5 million kWh | About $641,000 |
| Adaptive control that responds to activity | 10.9 million kWh | About $720,000 |
| Adaptive control plus shielding and warmer replacement lights | 11.5 million kWh | About $645,000 |

*Dollar savings assume $0.13/kWh and exclude implementation costs. Warmer lights use more electricity in this model for a given amount of useful light, so the final row has a different tradeoff.*

The first option is called **Phase 0**: prepare schedules for existing compatible controllers before buying new equipment. Its default minimum brightness is 50% on streets without presence sensing, with higher applicable safety floors retained. Exported schedules still need translation into the city's actual management system.

**These estimates depend on the baseline.** If the city already dims its lights overnight, the additional savings would be smaller. New adaptive controllers also do not pay for themselves through energy savings alone at ordinary hardware costs; the [playbook](docs/PLAYBOOK.md) explains that tradeoff.

### Darker streetlights are only part of a darker sky

*Skyglow* is the bright haze above a city at night. Streetlights contribute to it, but buildings, signs, stadiums, and other lights do too.

Nocturne's **Night Signal** proposes a common schedule those other lighting owners could follow. Its modeled benefits depend on their participation. The DC sky model currently borrows a streetlight-share assumption from Tucson; DC measurements are needed to establish the local share. Predicted star counts are illustrations from the model, not promises.

## More things to try

All of these examples use included data or generate their own files.

**Estimate the sky at six DC locations:**

```bash
nocturne sky
```

**Check upward light from an included synthetic fixture:**

```bash
nocturne bug examples/ies/synthetic-globe-4000lm-ulr15.ies
```

Here, “BUG” means **backlight, uplight, and glare**: where a fixture sends light.

**Create a trial plan, then export its first wave of schedules:**

```bash
nocturne pilot --seed "example-seed" --out plan.csv
nocturne schedule --plan plan.csv --wave 1 --out phase0
```

This creates `plan.csv`, then `phase0/programs.json` and an assignment CSV. For a real trial, publish the chosen seed before drawing the groups.

**Create a 30-night calendar:**

```bash
nocturne signal --date 2026-10-14 --ics curfew.ics --days 30
```

This writes `curfew.ics` and prints the first night's schedule as JSON. Signing the signal requires the optional `--key` setting; it is not signed by default.

**Run the full night simulation:**

```bash
nocturne simulate --out simulation-output
```

This runs multiple scenarios and writes results to a new folder. Allow several minutes.

**Try another city's clock:**

```bash
nocturne trace --site sydney --road local --start "2027-01-15 20:00" --end "2027-01-16 08:00"
```

There are 17 location presets. Changing the location does not supply that city's streetlight inventory; DC-specific sky maps and data remain DC-specific.

## What still needs real-world work?

- **Hardware and integration:** the controller is modeled in Python. Hardware firmware, field testing, and connections to municipal systems remain deployment work.
- **Local measurements:** traffic, fixture characteristics, sky conditions, electricity prices, and existing dimming policies need verification.
- **Safety evidence:** a crash-monitoring tool can flag concerning data; a “continue” result does not prove a lighting plan is safe.
- **Model limits:** the sky model simplifies the atmosphere and does not include terrain or buildings. Some inventory wattages are filled in from comparable fixtures.
- **Participation:** Night Signal is a protocol proposal, not an adopted city policy or an operating public service.

The [evidence review](docs/EVIDENCE.md) and [engineering reference](docs/ENGINEERING.md) explain the assumptions, discrepancies, and limitations in more detail.

## Go deeper

| Resource | What you will find |
|---|---|
| [DC playbook](docs/PLAYBOOK.md) | The proposed rollout, costs, measurement plan, and governance. |
| [Evidence review](docs/EVIDENCE.md) | Research behind the approach, including contrary evidence. |
| [Engineering reference](docs/ENGINEERING.md) | Control logic, specification corrections, security, test coverage, and detailed simulation results. |
| [DC inventory notes](data/dc/README.md) | Where the included data comes from and how it is processed. |
| [Recorded simulation report](out/report.md) | Results from the committed example run. |
| [Controller code](vdl7/controller.py) | How a modeled streetlight makes decisions. |
| [Command-line code](vdl7/cli.py) | Available commands, defaults, and input formats. |
| [Tests](tests/) | Checks for the controller and planning tools. |

To run the tests locally after the installation above:

```bash
python -m pytest -q
```

On Windows, use `.\.venv\Scripts\python.exe -m pytest -q`. The browser/Python parity test also needs Node.js and is skipped if it is unavailable.

Nocturne began as the reference implementation for **VD-DSL-SPEC-001 RevA, DC Dark-Sky Lighting Engineering Specification** (Christopher Woodyard, Vers3Dynamics, October 2026). The engineering reference preserves that specification-level detail.

## License

[MIT](LICENSE).
