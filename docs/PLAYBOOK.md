# Nocturne for Washington, DC: tonight, then the municipal rollout

**Start tonight with [DC Tonight](TONIGHT.md):** a consenting owner's existing switch or blind, a named handoff, and an honest morning record. `nocturne app --tonight` prepares this workflow. It can run independently of a streetlight programme. Public and federal assets are routed to their operators; their changes require separate decisions.

The longer-term municipal proposal below combines DC inventory aggregates with modeled scenarios and planning assumptions:

- **Streetlights:** DDOT's asset layer (`data/dc/`).
- **Crashes:** the District's crash layer.
- **Time and sky:** the node's clock and sky models.

These are planning estimates, not observed savings or a verified account of current DDOT operating schedules. The [integration gates](INTEGRATION.md) determine whether an exported schedule is ready for a responsible operator to import.

## The short version

1. **Much of the relevant infrastructure already exists.**
   - 97 % of DC's 72,512 active streetlights are LED, most already 2700K.
   - 96 % carry a node recorded as successfully registered (`CLIGHT_SCAN_SUCCESS_1`).
   - The LED luminaire models that make up most of the inventory specify DALI drivers.
   - Remote-control capability does not establish current schedules, permission to change them or compatibility with Nocturne's files. Confirm those with DDOT and its operator.
2. **Phase 0 targets compatible existing hardware.** Prepare and review a time-of-night schedule, establish the real baseline, then import through the responsible operator after the integration gates pass. The 2027 model (`nocturne business-case`) estimates:

   | | Modeled all-night static baseline | Modeled Phase 0 |
   |---|---|---|
   | Energy per year | 16.4 GWh | 11.5 GWh (−30 %) |
   | Saved per year | — | ≈ $641,000 at an ASSUMED $0.13/kWh |
   | CO₂ avoided per year | — | ≈ 1,500 t at an ASSUMED 0.30 t/MWh |
   | Streetlight skyglow | 1.00 | 0.70 |

   Streets without presence sensing never go below 50 %. Tunnel, underpass and under-deck lights stay static.
3. **Roll it out as a randomised trial with a brake.**
   - Four waves of 3,024 street segments (about 18,000 lights each), eight weeks apart.
   - Waves are stratified so every ward moves in every wave.
   - The assignment is seeded from a string published before the draw, so anyone can re-run it.
   - Before each wave, an exact test on night-time crashes can pause the rollout. It compares switched with not-yet-switched segments within each eight-week period, so the season (long, dangerous winter nights against short June ones) cannot hide a harm.
4. **Measure the sky as well as the electricity.** Six proposed observation sites can support a calibrated field study. Sensitivity and study duration depend on local variance, environmental controls and the number of valid nights; the example's 0.05 mag effect is not a field detection guarantee.
5. **Fix the globes.**
   - 27 % of DC's streetlight power, 1.08 MW, is in post-top globes. They are the streetlights' main source of uplight.
   - Specify U0 top-reflector kits, checked with `nocturne bug`.
   - Do the cells that matter most to the parks first (`nocturne sky --retrofits 20`).
6. **Coordinate the other lighting owners in parallel.**
   - In the cited Tucson study, streetlights contributed about 14 % of skyglow. DC's local share requires measurement.
   - Publish the **Night Signal** and recruit the other lighting owners: federal agencies, BIDs, sports venues, sign owners.
   - The model's star counts illustrate a scenario; they are not a DC forecast. Begin with willing owners through DC Tonight while wider participation and measurements are developed.

## Phase 0: weeks, existing nodes

| Step | What | Tool |
|---|---|---|
| 1 | Agree the class schedule and the unsensed floor (default 50 %) with DDOT's lighting engineers; adopt the firmware floors as policy | `vdl7/profiles.py`, `--floor` |
| 2 | Confirm, under the streetlight programme's contract, who may change schedules and how savings are counted; agree import and readback terms with the CMS operator | contract |
| 3 | For each node family on the poles, write its capability profile from the datasheet and confirm it on the bench (steps, time resolution, minimum stable level, level granularity, dusk/dawn source, behaviour on network loss, metered delivered level) | `examples/controllers/` as a template |
| 4 | Publish the seed text, then draw the waves | `nocturne pilot --seed "…" --out plan.csv` |
| 5 | Export wave 1's programmes against the node profile: they are adapted brighter-only where the node is coarser, or refused | `nocturne schedule --plan plan.csv --wave 1 --controller node.json --out phase0` |
| 6 | Record each gate in `phase0/readiness.json`: contract authority, CMS access, equipment test, photometric review, High-Injury Network assignment, rollback, operations. Approvals are bound to the files' hashes | `nocturne readiness phase0/readiness.json` (exit 0 only when every gate is recorded) |
| 7 | Translate into the CMS's import format and load; then read back what the CMS holds and compare. Any segment missing or darker than intended is an error | CMS import, `nocturne reconcile` |
| 8 | Open a 311 category ("street too dark at night") that routes to an operator override for that segment | `Priority.OPERATOR` override, audit trail |
| 9 | Before each wave: night-time crashes by segment, switched vs not yet switched within each period; pause and revert on a signal | `nocturne brake --plan plan.csv --crashes … --through …` |
| 10 | Switch the next wave; report energy from the nodes' own 15-minute metering | node metering outbox |

A registered node in the inventory is not evidence that steps 2, 3 and 6 are done. Nocturne does not connect to the CMS; it checks the files and records the people who decided.

**What would make the saving smaller:**
- The baseline assumes lights run at their commissioned maximum all night. If DDOT already runs a dimming schedule, Phase 0 saves that much less.
- The assumed energy price and grid factor scale the dollars and tonnes linearly.

**Power.**
- DC recorded 18,173 crashes in 2025. Between 44 % and 56 % happened after dark, depending on how the layer's timestamps are read.
- That is on the order of 0.002 night crashes per lit segment-night. Detecting a 20 % change at that rate needs roughly 190,000–240,000 segment-nights per arm (`nocturne pilot --power 0.0018 1.2`).
- Compared within periods, the wedge holds the equivalent of about 250,000 per arm at the first brake check and 590,000 at the second. With the error rate split over three checks, a real 20 % rise would pause the rollout at the first check with probability about 0.75–0.85, and by the second almost surely.
- The crash layer's segment ID field is empty, so join crashes to lit segments by location.

## Phase 1: adaptive control where it earns its keep

The VDL-7 firmware in this repository owns the curfew on the pole. It uses:
- its own astronomical clock and DST rule;
- signed profile bundles held in two flash banks;
- radar presence with a three-pole light carpet;
- live loop volumes;
- fail-safe modes that keep the schedule through any cellular or cloud outage.

The other half of the case:
- On energy alone, VDL-7 nodes do not pay back: with one on every pole, a node would have to cost under about $11 to repay itself in ten years (about $14 on local streets, where the deeper curfews are).
- Their case is light where people are and darkness where they are not: deeper curfews on local streets, alleys and park edges (local streets average 52 % instead of 58 %; park edges 32 % instead of 52 %), and the safety evidence for targeted light (EVIDENCE.md §1).
- **Start where that matters:** High-Injury Network segments, park and river edges, and residential streets that ask for it.

## Phase 2: optics and spectrum at replacement

- **Globes.** U0 top reflectors in the post-top globes remove a further 6–24 points of the streetlights' evening skyglow, depending on the place (`nocturne sky`).
- **Spectrum.** At replacement, 2200K on collectors, local streets and alleys, and PC-Amber at park and river edges, as Section 4 of the spec says. It costs about 5 % in energy and buys the largest cut in what the dark-adapted eye and the circadian system receive.
- **Trespass.** Check bedroom windows with `nocturne trespass` before choosing house-side shielding. DC records almost none today.

## Phase 3: the Night Signal

- **What it is.** One signed JSON feed and calendar each evening: dusk, dawn, the moment each phase begins, the Moon, and whether a heavy migration night is forecast. For each kind of non-street lighting, it gives the recommended output in each phase (`nocturne signal`).
- **Who to recruit first:**
  - **Federal partners.** NPS, GSA, the Architect of the Capitol, the Smithsonian. The monuments and federal buildings are DC's most visible lights, and Lights Out DC volunteers report a federal building among the worst bird-collision sites.
  - **Business improvement districts,** for signage and shopfronts.
  - **Stadiums and sports fields.**
  - **Billboard owners.**
- **On migration nights:**
  - BirdCast-style forecasts set the flag.
  - Facades and empty office floors go dark from dusk.
  - The same input signs migration events for the streetlights' presence classes.
- **Law.** France made curfews for non-residential lighting national in 2018. The District can start with voluntary adoption, then put curfew hours in code, with the signal as the compliance clock.

## Measurement and verification

- **Hardware.** Six sky-quality meters (SQM-LU-DL or TESS-W class), one at each place in `vdl7/skyglow.PLACES_DC`, logging every five minutes.
- **Method.** `nocturne verify station.dat --go-live YYYY-MM-DD` compares each night's change in brightness across the 23:00 curfew before and after go-live.
  - Within-night comparisons reduce some environmental variation; clouds, aerosols and other light sources can still change across the window. Use screened observations and appropriate controls rather than assuming cancellation.
  - A naive before/after comparison of the late-night sky is about ten times noisier.
- **Calibration.** Local brightness readings constrain the overall baseline (`nocturne sky --measured rock-creek=18.4 …`). They do not alone identify the streetlight share; use the source-isolation trials in [RESTORATION.md](RESTORATION.md) for attribution.

## Governance and equity

- **Ward balance.** Every ward is in every wave. Results are reported per ward.
- **Floors are code.** No signed bundle can take a street below its RP-8 class, or a High-Injury Network segment below 60 % (`FIRMWARE_MIN_FLOOR`, `FIRMWARE_MIN_HIN`).
- **Neighbourhood zones go both ways.**
  - Darker buffers around parks.
  - Brighter-for-longer nightlife corridors, e.g. U Street.
  - Both are signed overlays validated against the same floors (`ProfileBundle.zones`).
- **Overrides are logged.** Every override records who, when and why, and goes to the central system's audit trail. Only incident command can pull an emergency below 100 %.

## Other cities

- **Any city's clock.** The node runs on any city's POSIX TZ rule. It reproduces the IANA database for every zone one recurring rule can express, all but a handful of 498; zones it cannot (Gaza's and Hebron's Ramadan-linked switches) are refused at commissioning. Polar day and night are handled.
- **Presets.** 17 site presets (`nocturne trace --site sydney`).
- **Without an inventory.** `nocturne business-case --site X --fleet spec --lights N` sizes a fleet from the spec's assumptions.
- **With an inventory.** `tools/fetch_dc_inventory.py` is the template for turning a city's asset layer into `fleet.json` and `grid.csv`.
