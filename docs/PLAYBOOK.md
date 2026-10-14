# Nocturne for Washington, DC: what can start this quarter

This is the operational plan behind the code. Every number on this page comes from a command in this repository, run on DC's own data:

- **Streetlights:** DDOT's asset layer (`data/dc/`).
- **Crashes:** the District's crash layer.
- **Time and sky:** the node's clock and sky models.

Anything assumed is marked ASSUMED and can be changed with a flag.

## The short version

1. **The expensive part is already done.**
   - 97 % of DC's 72,512 active streetlights are LED, most already 2700K.
   - 96 % carry a networked node that has registered with the central system (`CLIGHT_SCAN_SUCCESS_1`).
   - The LED luminaire models that make up most of the inventory specify DALI drivers.
   - DC can already dim from a desk. It just doesn't have a policy for when.
2. **Phase 0 needs no new hardware.** Push the Nocturne time-of-night schedule to those nodes. On DC's fleet over the whole of 2027 (`nocturne business-case`):

   | | Today | Phase 0 |
   |---|---|---|
   | Energy per year | 16.9 GWh | 11.75 GWh (−30 %) |
   | Saved per year | — | ≈ $665,000 at an ASSUMED $0.13/kWh |
   | CO₂ avoided per year | — | ≈ 1,500 t at an ASSUMED 0.30 t/MWh |
   | Streetlight skyglow | 1.00 | 0.70 |

   Streets without presence sensing never go below 50 %.
3. **Roll it out as a randomised trial with a brake.**
   - Four waves of about 3,030 street segments (about 18,000 lights each), eight weeks apart.
   - Waves are stratified so every ward moves in every wave.
   - The assignment is seeded from a string published before the draw, so anyone can re-run it.
   - At each wave, an exact test on night-time crashes can pause the rollout.
4. **Measure the sky, not just the meter.** Put six sky-quality meters at the places the model reports on. The curfew-step method detects a 0.05 mag change in one season.
5. **Fix the globes.**
   - 26 % of DC's streetlight power, 1.07 MW, is in post-top globes. They are the streetlights' main source of uplight.
   - Specify U0 top-reflector kits, checked with `nocturne bug`.
   - Do the cells that matter most to the parks first (`nocturne sky --retrofits 20`).
6. **Then do what streetlights alone cannot.**
   - In the only city-scale measurement, streetlights were about 14 % of the light behind Tucson's skyglow.
   - Publish the **Night Signal** and recruit the other lighting owners: federal agencies, BIDs, sports venues, sign owners.
   - In the model, if they halve their light after 23:00, the stars visible after midnight at Rock Creek Park roughly double (≈ 208 → 421). Streetlights alone add ≈ 20.

## Phase 0: weeks, existing nodes

| Step | What | Tool |
|---|---|---|
| 1 | Agree the class schedule and the unsensed floor (default 50 %) with DDOT's lighting engineers; adopt the firmware floors as policy | `vdl7/profiles.py`, `--floor` |
| 2 | Confirm, under the streetlight programme's contract, who may change schedules and how savings are counted | contract |
| 3 | Publish the seed text, then draw the waves | `nocturne pilot --seed "…" --out plan.csv` |
| 4 | Load wave 1's programmes into the central system: per-class steps at dusk, fixed local times and dawn, with dusk and dawn from the node's own astronomical clock | `nocturne schedule --plan plan.csv --wave 1`, CMS import |
| 5 | Open a 311 category ("street too dark at night") that routes to an operator override for that segment | `Priority.OPERATOR` override, audit trail |
| 6 | At each wave: crashes by segment-night, switched vs not yet switched | `vdl7.pilot.brake` |
| 7 | Switch the next wave; report energy from the nodes' own 15-minute metering | node metering outbox |

**What would make the saving smaller:**
- The baseline assumes lights run at their commissioned maximum all night. If DDOT already runs a dimming schedule, Phase 0 saves that much less.
- The assumed energy price and grid factor scale the dollars and tonnes linearly.

**Power.**
- DC recorded 18,173 crashes in 2025. Between 44 % and 56 % happened after dark, depending on how the layer's timestamps are read.
- That is on the order of 0.002 night crashes per lit segment-night. Detecting a 20 % change at that rate needs roughly 190,000–240,000 segment-nights per arm (`nocturne pilot --power 0.0018 1.2`).
- The wedge has that by the end of wave 2.
- The crash layer's segment ID field is empty, so join crashes to lit segments by location.

## Phase 1: adaptive control where it earns its keep

The VDL-7 firmware in this repository owns the curfew on the pole. It uses:
- its own astronomical clock and DST rule;
- signed profile bundles held in two flash banks;
- radar presence with a three-pole light carpet;
- live loop volumes;
- fail-safe modes that keep the schedule through any cellular or cloud outage.

The other half of the case:
- On energy alone, radar nodes do not pay back: a node would have to cost under about $18 to repay itself in ten years.
- Their case is light where people are and darkness where they are not: deeper curfews on local streets, alleys and park edges (local streets average 52 % instead of 58 %; park edges 32 % instead of 52 %), and the safety evidence for targeted light (EVIDENCE.md §1).
- **Start where that matters:** High-Injury Network segments, park and river edges, and residential streets that ask for it.

## Phase 2: optics and spectrum at replacement

- **Globes.** U0 top reflectors in the post-top globes remove a further 7–23 points of the streetlights' evening skyglow, depending on the place (`nocturne sky`).
- **Spectrum.** At replacement, 2200K on collectors, local streets and alleys, and PC-Amber at park and river edges, as Section 4 of the spec says. It costs about 6 % in energy and buys the largest cut in what the dark-adapted eye and the circadian system receive.
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
  - Weather, season and aerosol cancel within the night, so a 0.05 mag change shows up in a single season.
  - A naive before/after comparison of the late-night sky is about ten times noisier.
- **Calibration.** The same readings replace the Tucson prior (`nocturne sky --measured rock-creek=18.4 …`). They tell DC what share of its sky its streetlights really are.

## Governance and equity

- **Ward balance.** Every ward is in every wave. Results are reported per ward.
- **Floors are code.** No signed bundle can take a street below its RP-8 class, or a High-Injury Network segment below 60 % (`FIRMWARE_MIN_FLOOR`, `FIRMWARE_MIN_HIN`).
- **Neighbourhood zones go both ways.**
  - Darker buffers around parks.
  - Brighter-for-longer nightlife corridors, e.g. U Street.
  - Both are signed overlays validated against the same floors (`ProfileBundle.zones`).
- **Overrides are logged.** Every override records who, when and why, and goes to the central system's audit trail. Only incident command can pull an emergency below 100 %.

## Other cities

- **Any city's clock.** The node runs on any city's POSIX TZ rule. It matches the IANA database for all 498 zones, and polar day and night are handled.
- **Presets.** 17 site presets (`nocturne trace --site sydney`).
- **Without an inventory.** `nocturne business-case --site X --fleet spec --lights N` sizes a fleet from the spec's assumptions.
- **With an inventory.** `tools/fetch_dc_inventory.py` is the template for turning a city's asset layer into `fleet.json` and `grid.csv`.
