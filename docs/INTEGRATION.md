# From exported schedules to an accountable import

A streetlight that the inventory records as having a registered networked node is **not** evidence that Nocturne's schedules can run on it. Whether they can depends on the central management system's import format, the node family and its firmware, the streetlight contract, the CMS operator's terms, and an engineer's review of every dimmed level. Nocturne cannot establish any of these. It can make each one an explicit, checkable step, and refuse to call a package ready until each is recorded.

**Nocturne never connects to a CMS or a light.** It writes files, checks them, and records who decided what.

## The workflow

```bash
nocturne pilot --seed "publish-before-drawing" --out plan.csv
nocturne schedule --plan plan.csv --wave 1 --controller node.json --out phase0
nocturne readiness phase0/readiness.json            # exit 0 only when every gate is recorded
# ... the integrator translates phase0/programs.json into the CMS import format and loads it ...
nocturne reconcile --programs phase0/programs.json --assignments phase0/assignments-wave1.csv \
                   --cms-programs cms-programs.json --cms-assignments cms-assignments.csv
```

| Step | Who | What Nocturne checks |
|---|---|---|
| Describe each node family | Integrator, from the datasheet; confirmed on the bench | The profile's fields and their consistency |
| Export against the profile | Planner | Every programme fits the profile, adapted brighter-only, or the export is refused |
| Record the gates | The named people responsible | Every gate approved (or not applicable) with a name, role, date and evidence reference; files unchanged since |
| Import | Integrator, in the CMS | Nothing: outside Nocturne |
| Read back | Integrator exports what the CMS holds | Every segment present and never darker than intended at any minute |

## Controller capability profiles

A profile declares what one node family and its CMS can hold. Two **invented** examples are in [`examples/controllers/`](../examples/controllers/). Replace their values with the datasheet's and set `verified` only after a bench test.

| Field | Meaning |
|---|---|
| `name`, `source` | The node family, and where these values came from (datasheet revision, test report) |
| `verified` | `true` once a bench or field test confirmed the values; the readiness report says when it is not |
| `dusk_dawn` | `astronomical` and/or `photocell`: how the node finds dusk and dawn |
| `max_steps_per_program` | Levels a programme may hold between dusk and dawn, counting the dusk level |
| `time_resolution_min` | Fixed-time steps must fall on this grid (1, 5, 10, 15, 20, 30 or 60 minutes) |
| `min_level_pct` | The lowest dimmed level the driver holds stably |
| `max_level_pct` | The highest level the node reaches (a multiple of `level_step_pct`) |
| `level_step_pct` | Level granularity, e.g. 10 for 10 % steps |
| `max_programs` | Distinct programmes the CMS or node can hold |

**Adaptation only adds light.** Where a programme is finer than the controller, `nocturne schedule --controller` rebuilds it on the controller's time grid taking the brightest level inside each slot, raises levels to the driver's stable minimum and rounds them up to its granularity, and merges neighbouring steps (the brighter level wins) where there are too many, choosing the merge that adds least light. Every adapted programme is checked to be at least as bright as the exported one at every minute of the night. The cost is energy, never light: the business case's Phase 0 saving becomes an upper bound, and `compatibility.json` records how many full-output hours each adaptation adds per night.

What cannot be adapted that way is **refused** and nothing is written: a level above what the node reaches, more programmes than it holds, or no dusk/dawn source.

## The readiness record

`nocturne schedule` writes `readiness.json` next to the programmes, with every gate pending and the SHA-256 of each file it wrote (`programs.json`, `compatibility.json`, the assignments). It never overwrites an existing record: approvals are evidence.

| Gate | The question it records an answer to |
|---|---|
| Contract authority | Under the streetlight contract, who may change schedules on these nodes, and have they agreed? |
| CMS access | Does the CMS operator's agreement allow import and readback, and who performs them? |
| Equipment test | Has each node family accepted these programmes on the bench, kept them through a network loss, and delivered the requested levels (metered)? |
| Photometric review | Has a licensed lighting engineer confirmed every dimmed level and transition meets the applicable standard (for example ANSI/IES RP-8)? |
| High-Injury Network | Are this wave's HIN segments identified from the city's list and given their `hin/` programmes? |
| Rollback | Can every node in the wave return to its previous programme within one night, tested? |
| Operations | Is a 311 "street too dark" route to an operator override staffed, and the crash brake scheduled? |

For each gate set `status` to `approved` (or `not_applicable`, with the reason as evidence) and fill `approved_by`, `role`, `date` (YYYY-MM-DD, not in the future) and `evidence` (a document or ticket reference). `nocturne readiness` exits 0 only when:

- every gate is recorded;
- `programs.json` is among the recorded files, and no recorded file has changed or gone missing since;
- every package file in the directory (`programs.json`, `compatibility.json`, `assignments*.csv`) is covered by the record, so a second wave exported into the same directory is not covered by the first wave's approvals;
- the recorded `compatibility.json` holds a controller profile, and every programme in `programs.json` is checked against it again, rather than trusting a summary someone could edit.

Change a programme after approval and the record fails: regenerate, and approve again. Export each wave to its own directory.

## Reconciling the CMS readback

After the import, export what the CMS reports it holds, in two files:

- `cms-programs.json`: `{"programs": {name: {"steps": [...]}}}`, the same shape as `programs.json`, with each step `{"at": "dusk" | "HH:MM" | "dawn", "level": percent}`;
- `cms-assignments.csv`: columns `segment,program`.

| Finding | Result |
|---|---|
| A segment in the wave missing from the readback | **Error** |
| A segment assigned a programme the readback does not contain | **Error** |
| A segment darker than intended at any minute of the night | **Error**, with the first such time and both levels |
| A different programme name that is never darker (e.g. a `hin/` variant) | Warning: confirm the mapping |
| Brighter than intended at some hours | Warning: safe, but the saving is smaller |
| Segments in the readback that are not in this wave | Warning |

A programme whose fixed-time steps fall between 12:00 and 15:59 is refused as input: such a step could come before or after dusk, so the level from dusk would be ambiguous. An assignments file with no segments is an error, not a pass. `nocturne reconcile` exits 0 only without errors. It compares files; it does not measure light. Spot photometry and the nodes' own metering confirm what the lamps deliver.
