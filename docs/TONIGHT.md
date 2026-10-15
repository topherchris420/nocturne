# DC Tonight: use the switch you already have

The immediate opportunity is light that has finished its job but remains on. A new luminaire, a city ordinance or access to DDOT's central system is unnecessary for a willing owner to stop a dedicated decorative circuit after closing or contain window spill with an existing blind.

DC Tonight makes that modest intervention executable: **one source → one responsible person → one explicit window → one morning record**. Its purpose is to turn intent into repeatable work. It does not establish that DC's light pollution has been solved.

## A first night that can actually happen

| When | Owner's action | Record |
|---|---|---|
| Before closing | Walk the property. Identify one separately controlled source whose light is unnecessary for the proposed window. For occupied rooms, consider closing existing blinds. | Location, circuit/window-group ID, baseline observation and responsible owner. |
| Before agreeing | Check the whole interval, including cleaning, deliveries and late users. Keep required security, exits, stairs, paths and occupied task lighting served. Check that one switch will not also cut useful light. | Permission, existing control, preserved service, and the person/setting for restoration. |
| At the agreed start | Recheck current need; perform the change only if it remains appropriate. Skip it if circumstances changed. | Actual start time with UTC offset, operator and evidence reference. |
| During the interval | Leave useful lights available. Restore the previous condition promptly if the change creates a problem. Check for a compensating floodlight or longer operating hours elsewhere. | Exception and restoration records. |
| At the morning handoff | Verify what persisted; restore the agreed daytime setting. Account for gaps in observation honestly. | Actual end, evidence, service retained and absence of compensating light. |

Start with a single source you can inspect. A visual walkthrough and control log can document an operating change. One photograph at the end does not establish that the condition persisted all night. Unobserved work stays unconfirmed.

Existing equipment can make the equipment cost zero; it does not make labour, coordination or review free. Never open electrical equipment, modify public lamps or improvise fixture covers as part of this workflow.

## Three useful ways to coordinate existing routines

**The closing handoff.** Add the decorative circuit and window blinds to the existing closing checklist. The last staff member checks current occupancy; the first staff member checks persistence and exceptions. An existing timer can perform a previously agreed switch, but the human check still matters. Cleaning and security staff help define the interval; their working light remains available.

**Keep the room, contain the spill.** Where an occupied room genuinely needs light, use an existing blind to interrupt the path through the window. This preserves the task light without claiming that the electrical load disappeared. DC Tonight reports window-group hours separately. A group is the specific set recorded by the owner, not a standardized area or brightness unit; do not use the count to rank buildings.

**A voluntary shared closing time.** A few consenting neighbouring buildings can agree a closing window and complete separate source records. That offers an achievable first block without a central control system. Build on Lights Out DC's existing campaign. Start with participants who can act; leave unwilling or unknown owners pending. For migration, consider earlier containment through dusk-to-dawn rather than treating the example's 22:00–06:00 as a scientific optimum or DC law.

These are proposed operating routines, not new scientific discoveries or validated DC interventions. The software's useful contribution is making the responsibility, exceptions and evidence visible.

## Route the sources you do not control

| Source | Useful action today | What cannot be promised today |
|---|---|---|
| District street/alley light shining into a window, operating during daylight or malfunctioning | Prepare a factual draft; submit it yourself through [DC 311](https://311.dc.gov/). Record location, pole type/ID if available, time, the actual problem and the resulting request number. | A repair or dimming. DDOT lists investigations/simple maintenance at 2–5 days and upgrades, including overly bright lights, at up to 12 months. |
| Federal building or monument | Identify the responsible property's facilities operator and request a review of existing schedules, unnecessary exterior lighting and window spill. | District authority over the asset or approval by the federal owner. |
| Private building you do not control | Ask its owner or facilities manager to review a specific source and a reversible change. Offer a clear observation rather than an accusation. | Consent, an actual change or any counted benefit before it happens. |
| Asset with an unknown owner | Establish responsibility before asking for a particular change. | That a visible light belongs to DDOT just because it is in DC. |

Drafts are generated for review only. No email, service request or calendar invitation is sent. An exported calendar is a local file with manual tasks; importing it does not control a device.

Municipal changes continue through [Nocturne's existing integration workflow](INTEGRATION.md): controller capability, contract/owner approval, engineering review, import and readback. Public/federal circuits are always request-only in DC Tonight, even if somebody ticks its permission box. That keeps this simple tool within its intended scope.

## Use the tools

After installing the repository:

```bash
nocturne app --tonight
```

Open a saved **DC Tonight project.json**, or use **Start fresh**. This is a different input format from a restoration project. Add sources in the form, build the plan, and download the project plus action sheet, calendar and empty receipts. Edits invalidate the displayed plan; build again before exporting. Downloads are your saved copy; the browser does not automatically persist work.

Command-line equivalent:

```bash
# Generate a blank editable project and empty packet; no fictional permissions.
nocturne tonight --out my-block

# Or learn from a fixed, fully fictional example.
nocturne tonight --example --date 2026-10-15 --out my-example

# After editing your real project, export to a NEW directory.
nocturne tonight my-block/project.json --out my-reviewed-night

# Next morning, fill the CSV, then reconcile against its ORIGINAL project.
nocturne receipts my-reviewed-night/project.json my-reviewed-night/receipts.csv
```

For another date, `--date YYYY-MM-DD` creates a new dated plan. Recheck availability and permission; a previously successful action is not permission for another night. Exports refuse to overwrite a directory. Keep private addresses, staff names and observations out of public repositories unless you intend to publish them.

### Project fields

Top level: `schema: "nocturne-tonight/1"`, `title`, `night_of` (evening date), `synthetic` (boolean), and `actions` (up to 200). Start from the example or browser rather than typing the full schema.

| Action fields | Meaning |
|---|---|
| `id`, `label`, `location`, `circuit`, `owner` | Stable action ID; human-readable source and location; unique physical circuit/window group; responsible person. One circuit/group may appear once. Use globally distinct IDs when combining owners. |
| `kind` | `switch_off`, `close_blinds`, or `report`. Partial dimming is outside this simple energy calculation. |
| `authority` | `private`, `district`, `federal`, or `unknown`. Only the private scope can become an owner task here. |
| `authorized`, `existing_control`, `service_reviewed` | Actual booleans. Missing fields default to false. These are owner declarations, not authenticated approvals or engineering certification. |
| `start`, `end` | `HH:MM` in America/New_York. The night runs noon-to-noon; times before 12:00 fall on the following day. End must follow start. |
| `preserve`, `rollback`, `evidence` | Specific service retained, restoration procedure and source of the walkthrough/baseline claim. Required for an owner-ready task. |
| `baseline_on` | For switching off: the whole controlled circuit would otherwise be on throughout the entire proposed window. A circuit already off at midnight cannot claim savings until 06:00. Shorten the window to its true baseline. |
| `watts`, `power_basis` | Actual input power for the entire controlled circuit, including drivers. Unknown is `null`. A meter/operating record and date are better than installed maximum watts. Missing power or basis leaves the energy benefit unquantified. |

Input times use real elapsed hours across daylight-saving changes. For example, 22:00–06:00 spans nine hours on the 2026 fall-back night and seven on the spring-forward night. A start/end inside the missing or repeated clock hour is rejected rather than guessed. Receipts use explicit UTC offsets, for example `2026-10-15T22:00:00-04:00`.

### The five-file packet

| File | Use |
|---|---|
| `project.json` | Exact input to retain with the evidence. |
| `plan.json` | Derived states, conditional estimates, routing drafts and SHA-256 fingerprint. |
| `action-sheet.html` | Portable, printable handoff for people doing the work. |
| `handoff.ics` | Two events per owner-ready action: start and morning check. Missing-owner and public-asset actions do not become switch events. Fictional calendars label every event as a demo. |
| `receipts.csv` | One blank outcome row per owner-ready action, tied to the plan fingerprint. |

The fingerprint detects mixing or editing plans within this workflow. It does not prove the observer's identity, prevent fabrication or establish that a physical switch moved. Store original evidence separately; the CSV contains references, not uploaded photos or meter files.

### What the receipt can claim

Keep the exported CSV columns in order. `status` accepts blank, `completed`, `skipped` or `rolled_back`. Every nonblank outcome needs an `observer` and an `evidence` reference. A completed outcome also needs actual `started_at`/`ended_at` inside the reviewed window and `yes` for both `service_preserved` and `no_rebound`.

- Blank/missing completion, skipped and rolled-back actions receive no estimated benefit. A rollback deliberately receives no credit even if it briefly reduced light.
- A completed claim with missing/negative service or rebound confirmation becomes `needs_review` and receives no credit. Investigate and restore as necessary.
- A supported self-report receives only its recorded elapsed interval. For a complete circuit switch-off, estimated electricity reduction is **input watts × recorded hours / 1,000**. Its counterfactual baseline is still an assumption.
- Closed blinds receive **zero electricity credit**. The report shows elapsed window-group hours without asserting a measured amount of light contained.
- Unknown circuit power is listed as unquantified, not silently included in a complete total. No percentage reduction in skyglow, star count or birds killed is inferred.

`nocturne receipts` exits 3 for unconfirmed work or review concerns, 2 for invalid input and 0 when all eligible rows are accounted for. All-skipped work can correctly exit 0 with zero benefit; this is an accounting result, not success in reducing pollution.

For scientific effect estimates, use [the existing randomized source-attribution workflow](RESTORATION.md) with consenting owners, calibrated observations and environmental controls. Keep local spill, energy, sky brightness and collision outcomes as different measurements. Phone cameras on automatic exposure are not sky photometers.

## Verified sources and limits

Checked October 15, 2026:

| Source | What it supports |
|---|---|
| [DDOT street and alley light repair](https://ddot.dc.gov/service/street-and-alley-light-repair) | 311 reporting, identifying the asset/problem, request tracking and published response-time categories. |
| [Lights Out DC campaign](https://www.lightsoutdc.info/) | An existing local campaign linking DarkSky DC, City Wildlife and DC Bird Alliance; owners can participate now. No affiliation with Nocturne is implied. |
| [City Wildlife](https://citywildlife.org/programs/lights-out-dc/) | Local collision monitoring and building-owner light-abatement work. |
| [Cornell BirdCast](https://birdcast.org/lights-out/) | Nonessential lighting reduction, blinds, task lighting and dusk-to-dawn migration guidance. DC Tonight uses its broad March 1–June 15 and August 15–November 30 seasons as context, never as a live forecast. |

The 22:00–06:00 example is an editable demonstration, not an adopted curfew. Local source contributions and avoided environmental harm are not known from this workflow. Changes to opaque blinds can also have other operational effects, which the owner needs to assess. A citywide reduction still requires participating owners, measured outcomes and appropriate municipal/federal decisions. The useful first step does not need to wait for all of those decisions.
