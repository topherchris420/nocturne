# Nocturne · dark skies for a whole city, starting with the lights it already owns

Nocturne began as the reference firmware for the VDL-7 streetlight controller in **VD-DSL-SPEC-001 RevA, *DC Dark-Sky Lighting Engineering Specification*** (Christopher Woodyard, Vers3Dynamics, Oct 2026). The spec's rule is that **the node, not the CMS, owns the curfew**. Every VDL-7 carries its own astronomical clock, the city's DST rule, a signed profile bundle and an event store, so a cellular or cloud outage changes only *which events arrive*, never whether the lights dim.

This version turns that firmware into a program a city can start this quarter:

- **It runs on DC's real fleet.** The business case, the sky model and the pilot plan read DDOT's own streetlight asset layer (72,512 active lights) and the District's crash data, not assumed wattages.
- **It starts with no new hardware.**
  - DC's lights are already 97 % LED, and 96 % carry a networked node registered with the central system.
  - *Phase 0* pushes the Nocturne schedule to those nodes. On DC's fleet over a full year that saves **≈ 5.3 GWh and ≈ $690,000** (at an ASSUMED $0.13/kWh) and cuts streetlight skyglow by **31 %**.
- **It rolls out as a randomised trial with a brake.**
  - Four waves of about 3,000 street segments each, with every ward in every wave.
  - The assignment is reproducible from a seed text published before the draw.
  - An exact test on night-time crashes at every wave can pause the rollout.
- **It measures the sky, not just the meter.** The curfew-step method reads sky-quality-meter logs and detects a 0.05 mag change in a single season.
- **It goes beyond the streetlights, because it has to.**
  - In the only city-scale measurement, streetlights were about **14 %** of the light behind Tucson's skyglow.
  - The **Night Signal** is a signed public feed and calendar that lets every facade, sign, office floor, stadium and federal building keep the same curfew, and dims for bird-migration nights.
  - In the model for Rock Creek Park, streetlights alone add about 20 stars overhead after midnight. A shared curfew roughly **doubles** them.
- **It works in any city.**
  - The node's clock matches the IANA database for all 498 time zones.
  - Polar day and night are handled.
  - 17 city presets are built in.

**Start here:**
- [docs/brief.html](docs/brief.html) is the interactive decision brief: savings at your own energy price, a street through the night, the sky at six DC places, and the rollout. Rebuild it with `python tools/make_brief.py`.
- [docs/PLAYBOOK.md](docs/PLAYBOOK.md) is the DC plan, phase by phase.
- [docs/EVIDENCE.md](docs/EVIDENCE.md) covers what the research says, including where it cuts against us.

> **Status: prototype.** The firmware is a Python reference model of the behaviour, structured to port to C on a Cortex-M33; it is not certified firmware. Energy prices, grid emission factors, aerosol load, luminaire uplight and the network simulation's traffic and pedestrian curves are inputs marked ASSUMED. Every one can be changed from the command line.

![Mean output by road class](out/night_profile.png)

```
nocturne-vdl7/
├── vdl7/                   the node
│   ├── controller.py       the 1 Hz loop: mode ladder, arbitration, zones, migration, slew, CLO, SAFE clock, alarms, metering
│   ├── clock.py            NOAA solar position, POSIX TZ rule engine (any city), RTC holdover + counter, photocell
│   ├── profiles.py         road-class profiles, phases, floors, zone overlays, tunable-white mix, bundle validation
│   ├── events.py           signed, addressed, sequenced events; monotonic TTLs; anti-replay window
│   ├── cms.py              what the CMS signs and sends: events, overrides, geofences, bundles
│   ├── security.py         Ed25519 signing and key files (HMAC bench signer only on request)
│   ├── driver.py           DALI-2/D4i two-channel driver, 0-10 V, NC relay, failure level, metering model
│   ├── mesh.py             Wi-SUN segment mesh: 12-hop gateway reachability, 3-hop carpet, flood relay
│   ├── spectral.py         LED spectra; Rayleigh, scotopic, Mie, melanopic-DER, eye-weighted scattering
│   ├── sites.py            17 cities: latitude, longitude, POSIX TZ rule
│   └── bench.py            single-node bench with a modelled sky and CMS
├── vdl7/                   the city
│   ├── annual.py           a year of nights for a whole fleet: energy, cost, carbon, light, skyglow, break-even
│   ├── skyglow.py          single-scattering sky model; brightness, naked-eye limit and stars at named places
│   ├── photometry.py       IES LM-63 files, TM-15-11 BUG ratings, window trespass, CIE 150 and sleep limits
│   ├── nightsignal.py      the signed public curfew feed, subscriber logic, iCalendar, migration alerts
│   ├── observe.py          the Moon, sky-quality-meter logs, curfew-step difference-in-differences
│   ├── pilot.py            stepped-wedge randomisation, exact safety brake, power
│   ├── schedule.py         Phase 0: per-class programmes for the existing networked nodes
│   ├── demand.py           traffic and pedestrian curves (Section 6.4)
│   └── cli.py              the `nocturne` command
├── data/dc/                DC's streetlights from DDOT's asset layer: fleet, 550 m grid, 12,106 street segments
├── tools/                  fetch_dc_inventory.py (refresh data/dc), make_example_ies.py, make_brief.py
├── examples/ies/           synthetic photometry for trying `nocturne bug` and `nocturne trespass`
├── sim/run_night.py        400-node night simulation, 9 scenarios, scaled to 75,000 lights
├── tests/                  192 tests: the Section 6.2 table, the firmware extensions and every city tool
├── console/index.html      the operator console as a standalone page (parity-tested against the Python)
├── docs/                   brief.html (the decision brief), PLAYBOOK.md (the DC plan), EVIDENCE.md (the research)
└── out/                    simulation results: summary.json, report.md, timeseries.csv, charts
```

## Run it

```bash
pip install -e ".[dev]"                 # Python 3.10+; cryptography is the only runtime dependency
pytest -q                               # 192 passed in about a minute

# the city
nocturne business-case                  # 2027 on DC's real fleet; --price, --co2, --floor, --site, --fleet spec
nocturne schedule --plan plan.csv --wave 1 --out phase0/   # Phase 0 programmes for the central system
nocturne sky --retrofits 10             # the sky at six DC places; --measured rock-creek=18.4 to calibrate
nocturne bug examples/ies/synthetic-globe-4000lm-ulr15.ies           # B2-U4-G2: fails U0
nocturne trespass examples/ies/synthetic-roadway-6000lm-u0.ies --tunable
nocturne signal --date 2026-10-14 --migration --ics curfew.ics --days 30
nocturne pilot --seed "text published before the draw" --out plan.csv
nocturne pilot --power 0.0018 1.2       # segment-nights to detect a 20 % change in night crashes
nocturne verify station.dat --go-live 2026-11-01

# the node
nocturne trace --road local --offline-at 22:15 --event emergency@00:40:30
nocturne trace --site sydney --road local --start "2027-01-15 20:00"
nocturne spectral                       # Section 4 metrics; add --spd name=lm79.csv for a measured engine
nocturne simulate --out out             # all scenarios, about 4 min on 4 cores
nocturne keygen --out cms_key.pem       # CMS signing key; prints the public key for the nodes
nocturne bundle --key cms_key.pem --version 2 [--zones zones.json] --out bundle.json
```

## What DC gets (`nocturne business-case`, `nocturne sky`)

A full year (2027) on DDOT's fleet: 72,183 dimmable lights, 4.05 MW at their commissioned output, and 4,162 hours with the sun below −3°.

| Strategy | MWh / yr | Energy | Light | Streetlight skyglow | Saved / yr (ASSUMED $0.13/kWh) | tCO₂ / yr (ASSUMED 0.30 t/MWh) |
|---|---|---|---|---|---|---|
| Today: full output dusk to dawn | 16,866 | 1.00 | 1.00 | 1.00 | — | — |
| **Phase 0**: schedule on the existing nodes | 11,589 | 0.69 | 0.69 | 0.69 | $686,000 | 1,583 |
| **Phase 1**: VDL-7 adaptive (radar, live loops) | 11,134 | 0.66 | 0.66 | 0.67 | $745,000 | 1,720 |
| + top reflectors in the post-top globes (U0) | 11,134 | 0.66 | 0.66 | 0.58 | $745,000 | 1,720 |
| **Phase 2**: + warm spectrum at replacement | 11,819 | 0.70 | 0.66 | 0.54 | $656,000 | 1,514 |

**How to read the phases:**
- **Phase 0.** Streets without presence sensing never go below 50 % (`--floor`). It pays back in three years if integration costs under about $2.1 M.
- **Phase 1.** Radar nodes do *not* pay back on energy alone (break-even about $13 per node over ten years). Their case is light where people are and deeper darkness where they are not.

**After midnight**, full Nocturne removes 58–62 % of the streetlights' contribution to the zenith sky at six places. The figures below use Tucson's measured share (streetlights ≈ 15 % of artificial light) until DC calibrates with its own meters:

| Place, after midnight | Sky today (mag/arcsec²) | Nocturne | Nocturne + Night Signal | Stars overhead: today → Nocturne → + Signal |
|---|---|---|---|---|
| Rock Creek Park | 17.81 | 17.91 | 18.57 | 208 → 228 → 421 |
| U.S. National Arboretum | 17.59 | 17.69 | 18.36 | 169 → 186 → 346 |
| Kenilworth Aquatic Gardens | 17.62 | 17.72 | 18.38 | 173 → 190 → 355 |
| Anacostia Park | 16.91 | 17.01 | 17.69 | 88 → 97 → 185 |
| Theodore Roosevelt Island | 17.18 | 17.29 | 17.96 | 114 → 127 → 239 |
| National Mall | 16.84 | 16.94 | 17.62 | 81 → 90 → 174 |

In the "+ Night Signal" column, the rest of the city's lighting halves its output after 23:00 (`--cut`). The model and its limits are in `vdl7/skyglow.py`.

## The control loop (Section 2.4)

`VDL7Controller.tick(mono, dt)` runs once per second and determines everything the node does:

| Step | What the code does | Spec |
|---|---|---|
| 1 Mode | `SAFE` if the RTC isn't trusted; `ONLINE` if backhaul heard ≤ 15 min ago; `MESH` if a gateway path is ≤ 15 min old; otherwise `AUTONOMOUS` | 5.2 |
| 2 Lit | Lit when the sun is below −3° on the node's own clock **or** the photocell reads dark. The photocell can switch lights on early but can never hold them off. In SAFE mode the photocell alone decides | 2.4 |
| 3 Phase | Local civil hour on the city's own POSIX TZ rule gives the phase, which gives the base level: the class's, or its neighbourhood zone's from the signed bundle. On a migration night, presence classes hold their 22:00 level | 2.2 *(zones and migration are extensions)* |
| 4 Activity | Loop volume ÷ design volume, used only in ONLINE or MESH and only while under 15 min old. Presence (90 s) or carpet (60 s) sets A = 1 on occupancy classes, A ≥ 0.5 on arterials and collectors | 2.3, 5.2 |
| 5 Raise | `target = max(base, base + (cap − base) × A)` | 2.4 *(clamped, see below)* |
| 6 Weather | Rain: `max(target, min(cap, target + 15))`; fog and snow are logged with no boost | 2.3 |
| 7 Floor | Class floor; 60 % on the High-Injury Network | 2.2 |
| 8 Emergency | 100 % inside an active, addressed geofence | 2.3 |
| 9 Override | Highest priority wins; only incident-command priority can pull an emergency below 100 %. Who, when and why are logged | 2.4, 5.4 |
| 10 Slew | Up 25 %/s, down 1 %/s | 2.4 |
| 11 CLO | drive = level × (0.86 → 1.00 over 100,000 h) | 2.4 |
| 12 Output | Two DALI channels with the tunable-white mix; NC relay; DALI failure level; checkpoint every 60 s; alarms; 15-min metering | 4.3, 5.1, 5.2 |

## Where this code departs from the spec, and the spec text to change

An independent review of the first version against the spec found places where following the spec literally is unsafe or ambiguous. The code fixes each one, and each has a test.

1. **Activity and rain could dim a street (§2.4 steps 5–6).** For the local, alley and park classes the evening level is above or at the boost cap (local: 80 vs 70). Read literally, `base + (cap − base) × A` takes a local street from 80 to 70 % when a pedestrian walks in, and rain takes a park edge from 60 to 50 %. The code clamps both so they never lower the light (`EXT-DIM-4`). **Spec change:** add `max(base, …)` to steps 5 and 6.
2. **SAFE mode could misplace the curfew after a long cut (§5.2, §5.3, R-FS-3).** Per §5.2 the clock is lost only when the supercap drains, after more than 7 days. A flash checkpoint from before such a cut can't be dated, yet using it as if no time had passed moved the curfew by however long the power was off. The checkpoint now stores the RTC counter, and the node resumes from it only when the counter rode through the cut and can measure the gap (`R-FS-3`). After an RTC reset the node holds the 22:00 level until its photocell sees dusk (`EXT-FS-5`). **Spec change:** R-FS-3 should state that the RTC counter survived the cut.
3. **SAFE mode ran 8 minutes early (§5.3 step 5).** It counted from the photocell dusk but used a midpoint learned from the −3° sun. The node now learns the midpoint and night length from its photocell's own dusk and dawn on clocked nights. The clockless curfew lands at 22:58 (`R-FS-3`, `EXT-FS-4`).
4. **A dead node on the High-Injury Network fell below 60 % (§5.2).** The driver failure level is now the higher of the class's 22:00 level and 60 % on HIN segments (`EXT-FS-6`).
5. **Signed messages need more than a signature (§2.3, §5.4).** See *Message security* below for the design.
   - Every event is addressed to one street segment, optionally narrowed to the geofence nodes within it, and nodes ignore anything else. Malformed targets match nothing (`EXT-SEC-5`, `EXT-SEC-10`).
   - Events carry the segment's sequence number, checked against an anti-replay window kept in flash (`EXT-SEC-6`, `6b`, `6c`).
   - With a trusted clock, an event expires at issue time + TTL, not receipt + TTL. Nodes refuse events that expired before they arrived or claim a future issue time (`EXT-SEC-7`, `EXT-SEC-11`).
   - Bundles are type-checked and bounds-checked against firmware-minimum floors, completeness, mix sums and the 400-day validity before they are stored. The anti-rollback version survives even a fall back to the factory profile (`EXT-SEC-3`, `4`, `12`, `13`).
   - When the store is full, emergencies and overrides are evicted last, and unknown event kinds are ignored (`EXT-SEC-8`).
   - Override audit records (who, when, why, cancelled) go to the CMS (`EXT-SEC-9`).
6. **Weather must not teach the node a false dusk (§5.3).** A photocell dusk or dawn more than 45 min from the sun's is treated as weather and not learned. In SAFE mode, a dusk more than 45 min off yesterday's is replaced by the expected time (`EXT-FS-9`, `EXT-FS-10`).
7. **Number corrections.** §6.2 says "24 acceptance tests"; the firmware suite (`tests/test_controller.py`) has 82, and the city tools add 110 more. The table's 18 rows become 19 tests, because R-MESH-1/2 is split in two; the rest are extensions. The Section 6.3 and Section 4 figures are reconciled below.
8. **The clock is hard-wired to one city (§2.4, R-CLK-1).** The spec compiles in `EST5EDT`. The node now carries any POSIX TZ rule (`NodeConfig.tz`). Where the sun never crosses −3° (Tromsø in December, Reykjavik in June), the learning code used to crash; now the lights follow the sun and nothing is learned from a night with no dusk (`EXT-CLK-4` to `10`). **Spec change:** make the rule a commissioning parameter.

## Acceptance suite

`test_R_*` covers the 18 rows of the Section 6.2 table, with R-MESH-1/2 split into two tests. `test_EXT_*` covers requirements stated elsewhere in the spec that the table omits, plus the safety fixes above.

| Section 6.2 row | Test checks |
|---|---|
| R-CLK-1 | Firmware POSIX DST rule matches the IANA database at every 6-hour step, 2024–2030 (10,228 checks) |
| R-CLK-2 | Sunrise and sunset in Oct, Dec and Jun within 3 min; dusk and dawn are the −3.00° crossings; the controller switches on at that crossing with the photocell blinded |
| R-CLK-3 | Trusted at 1 year, not at 4; never before the first sync; 7-day supercap; longer cut resets the clock and counter |
| R-DIM-1 | Arterial at 60 % at 23:30 |
| R-FS-1 | Total outage: AUTONOMOUS, local street at 30 % at 01:00 |
| R-FS-2 | Backhaul-only loss: MESH mode applies an emergency at 100 % |
| R-FS-3 | Power cut at 21:00 zeroes the monotonic clock; from the photocell and checkpoint alone the node lands the curfew within 10 min (actual: 2 min early) |
| R-ADP-1 | Local street 30 → 70 % in under 2 s, back to 30 % after hold and fade |
| R-ADP-2 | Arterial at 50 % + 50 % × (150/300) = 75 % |
| R-ADP-3 | Loop boost kept for one 15-min slot after backhaul loss, then dropped |
| R-SAF-1 | HIN floor wins over the rain boost |
| R-SAF-2 | Fog and snow: no boost |
| R-SAF-3 | A blocked photocell cannot keep the lights off at night |
| R-SAF-4 | Storm darkness at 14:00 under 3 lx: lights on at the evening level |
| R-EM-1 | Emergency in SAFE mode expires on monotonic time |
| R-EM-2 | A planned override cannot lower an emergency; incident command can; cancelling restores it |
| R-CLO-1 | Drive 86 % new, 100 % at 100,000 h |
| R-MESH-1/2 | 12-hop budget; broken-path isolation; 3-hop carpet |

The extensions cover:
- **Dimming:** the full table, DST and phase boundaries, the boost clamp.
- **Fail-safe:**
  - clockless cold boot and RTC reset;
  - a hung controller falling to the HIN-aware failure level through the driver watchdog;
  - one hello leaving SAFE, and loop handling by mode;
  - storm darkness rejected while learning and in SAFE mode.
- **Adaptive:** presence on arterials, the light carpet.
- **Security:**
  - forged, tampered, unsafe, wrongly typed, expired and rolled-back bundles;
  - misaddressed, malformed, replayed, reordered and stale events, and CMS failover;
  - store eviction, cancellations, override priority, and the audit trail.
- **Tunable white:** the full mix.
- **Hardware:**
  - photocell 15/40 lx with 60 s debounce, and the 0–10 V path;
  - tilt, driver-fault, day-burner, cycling and stuck-photocell alarms;
  - metering that survives a dead link and a reboot;
  - hour meter and tilt baseline kept in flash.
- **Spectral:** limits, and round-tripping a measured spectrum.

CI runs the suite on Python 3.10–3.13 (`.github/workflows/tests.yml`).

### Beyond the firmware

| File | Tests | What they hold the code to |
|---|---|---|
| `tests/test_anycity.py` | 61 | **The POSIX rule engine against the IANA database.** For every zone on Earth, 2027–2030, mid-month and one second either side of every transition. Each of the 17 presets is checked every 6 h, 2024–2030. **Rule forms:** Jn/n, quoted names, `/24` and negative-DST. **Curfew at 23:00 local:** Sydney, Adelaide, Paris, Tucson. **Polar latitudes:** polar night and the midnight sun. **SAFE mode:** in the southern hemisphere. **Zones:** overlays, refused unsafe overlays, and the HIN floor inside a dark zone. **Migration nights.** |
| `tests/test_photometry.py` | 9 | Zonal lumens against closed forms; LM-63 corners; symmetry expansion; front/back split; TM-15 thresholds; inverse-square and cosine laws; window trespass; globes vs reflector retrofits |
| `tests/test_annual.py` | 7 | One night against the 400-node simulation; the year's shape; the order of the strategies; the unsensed floor; any city, including polar ones |
| `tests/test_skyglow.py` | 8 | Kernel against the closed-form near field (0.5 %); near and far slopes; the DC grid against the fleet; every lever in the right direction; calibration; the streetlights-alone vs shared-curfew claim; retrofit ranking |
| `tests/test_observe.py` | 11 | The Moon against PyEphem at the 2026 eclipses; log formats; twilight, Moon and cloud filters; a planted 0.12 mag curfew effect recovered from a season of synthetic readings with clouds and moonlight; a null effect |
| `tests/test_pilot.py` | 6 | DC's 12,106 segments randomised reproducibly and in balance; the exact test's size and power; the brake; the power formula |
| `tests/test_nightsignal.py` | 7 | Phase times through the fall-back night and in Sydney; signature; what each kind of light is told; iCalendar; migration alerts reaching the streetlights |
| `tests/test_console_parity.py` | 1 | The console's JavaScript controller against the Python one, level for level: nine scenarios, twenty checkpoints. Skipped without Node.js |

## Simulation results (Section 6.3)

`sim/run_night.py` uses the spec's layout (and reproduces every earlier scenario to the last digit after this version's firmware changes): 4 streets × 20 poles per class at 30 m spacing, 400 VDL-7 nodes, run through the night of 13–14 October 2026 in 10-second steps. A modelled CMS sends 15-minute hellos and one signed loop-volume message per segment. Seeded pedestrians walk 4–14 poles. Results are scaled to 75,000 lights by the Section 6.4 class mix.

| Scenario | Energy vs today | Spec 6.3 | Light vs today | Spec 6.3 | Skyglow index |
|---|---|---|---|---|---|
| Today: static 100 %, current CCT | 1.00 (55.6 MWh) | 1.00 | 1.00 | 1.00 | 1.00 |
| Adaptive dimming only | 0.67 | 0.65 | 0.67 | 0.65 | 0.67 |
| + U0 optics | 0.67 | 0.65 | 0.67 | 0.65 | 0.54 |
| + warm spectrum (full Nocturne) | 0.73 | 0.70 | 0.67 | 0.65 | 0.49 |
| Full Nocturne, 7-hour carrier outage | 0.70 | 0.68 | 0.65 | 0.63 | 0.47 |
| Same hardware, cloud-dependent control, same outage | 1.02 | 1.00 | 0.95 | 0.92 | 0.70 |
| Full Nocturne, CAD incident on one local street | 0.73 | — | 0.68 | — | 0.49 |
| Full Nocturne, rain 23:00–02:00 | 0.77 | — | 0.71 | — | 0.51 |
| Full Nocturne, heavy-migration night (Night Signal at 18:00) | 0.71 | — | 0.65 | — | 0.48 |

The skyglow waterfall goes 1.00 → −0.326 (dimming) → −0.135 (U0 optics) → −0.052 (warm spectrum) → **0.49**. The saving is 15.1 MWh per night, about **5.5 GWh a year** if every night were an October night on the spec's assumed fleet. `vdl7/annual.py` replaces both assumptions: on DC's real fleet (4.05 MW, against the spec's 4.44 MW) over every night of a real year, the adaptive saving is 5.7 GWh.

**How these compare with the spec.** Every row is within 2–3 points of the printed Table 6.3, but they don't match exactly, and the spec's prose figures should be updated to these or to a re-run on real DDOT data:

| Spec says | This version |
|---|---|
| 35 % less light | 33 % |
| 30 % less energy | 27 % |
| About 6 GWh a year (16.8 MWh per night) | 5.5 GWh (15.1 MWh per night) |
| Spectrum step "4 points" of skyglow | 5 points |

The boost clamp explains 0.8 of a point: with it removed, the dimming row is 0.661 / 0.663. The rest of the gap isn't identified, and the run that produced the printed table isn't available to compare against.

The cloud-dependent row now uses the same luminaires as the outage row, so it isolates the control architecture. Failing bright for seven hours costs 30 points of delivered light: 0.95 against 0.65.

![Outage comparison](out/outage_comparison.png)
![Skyglow waterfall](out/skyglow_waterfall.png)

## Spectral model (Section 4)

`vdl7/spectral.py` builds generic LED spectra on the Planckian locus:
- white: a 450 nm pump plus two broad phosphor bands, fitted to Duv ≈ 0;
- PC-Amber: a 600 nm phosphor with a 0.4 % residual pump;
- narrow-band amber.

For each spectrum it computes, per photopic lumen:
- Rayleigh scatter;
- skyglow weighted by scotopic sensitivity;
- Mie (λ⁻¹·³) scatter;
- CIE S 026 melanopic DER.

The model comes close to the Section 4 claims for 3000 → 2700K: −11 % perceived skyglow against the spec's −10 %, and −12.5 % melanopic against −11 %. It matches PC-Amber exactly: −75 % and −85 %. **It does not reproduce the 2700 → 2200K figures:**

| 2700 → 2200K | Spec §4 | Model |
|---|---|---|
| Perceived skyglow | −22 % | −30 % |
| Melanopic | −23 % | −35 % |

**Mie scatter also differs:**

| Mie scatter, 2200K | Spec §4 | Model |
|---|---|---|
| vs 4000K | 4 % less | about 10 % less |
| vs 3000K | "about the same" | 5 % less |

Both metrics are dominated by the 450–520 nm region, so small differences in pump and phosphor shape move them a lot. Neither set of numbers is a measurement. Load the LM-79 spectra of the engines you'll actually procure with `nocturne spectral --spd name=file.csv` and use those figures in Section 4.

## Message security (Sections 2.1, 2.3, 5.4)

The spec already groups nodes by street segment, with one LwM2M message per segment. The protocol follows that grouping:

- **Signing.** The CMS signs every bundle and event with Ed25519. Nodes verify before storing anything. Mesh relays forward the original bytes and never re-sign.
- **Addressing.** Every event names one segment and, for a geofence, the nodes within it. A 400 m CAD geofence spanning three segments goes out as three messages with the same event id.
- **Sequencing.** The sequence number is the CMS's counter *for that segment*, with a failover epoch in the high 32 bits. Each node keeps a 64-wide sliding window over its own segment's counter. The window tolerates reordering among the few messages a segment gets, however much traffic the rest of the city generates. A standby CMS that lost the counters bumps the epoch.
- **Freshness.** With a trusted clock, events expire at issue time + TTL. In SAFE mode, receipt + TTL is the only clock available.
- **Acknowledged uplink.** Metering, alarms and audit records stay in a flash outbox until the CMS acknowledges them. A link that dies before the node notices loses nothing.

## SAFE mode without a clock (Sections 5.2, 5.3)

On every clocked night the node records the local time of its photocell's dusk and dawn, and keeps the midpoint and night length in flash. Transitions more than 45 min from the sun's are treated as weather and not learned. In SAFE mode it estimates the night-hour as **learned midpoint + (time since photocell dusk − previous night length / 2)**, so it counts from the same kind of dusk it learned from.

If it reboots mid-night, it resumes from the 60-second flash checkpoint plus the gap the RTC counter measured. If the counter itself was lost, it holds the 22:00 level until the next dusk.

On the second and later clockless nights, a dusk more than 45 min off the previous one is replaced by the expected time. On the first clockless night there is nothing to compare against, so storm darkness that runs straight into night will start the count early. Accuracy after a long outage also degrades with the season, by roughly 1–2 minutes per day of outage near the equinoxes, until the next time sync.

## Porting notes

- The loop keeps fixed-size state: a 64-entry event store, a 64-bit replay bitmap, a 672-record uplink ring in flash, and 256-line log and audit rings.
- It reads no wall clock outside `tick` and `receive`, and keeps every timer in monotonic seconds.
- On the MCU, the replay-window top belongs in FRAM or the secure element's monotonic counter, because it is written on every accepted event. The DALI failure level is written only when it changes.
- Python allocates small lists per tick; the C port should use static buffers.

## Known limits

**Firmware**
- Carpet events between neighbouring nodes are not signed here. The spec's device keys would sign them, but that is out of scope for this model.
- The CMS side (TALQ, LwM2M, DTLS) is modelled only by the messages it signs. Phase 0 still needs the schedule translated into the import format of DC's central management system.

**Business case**
- The baseline assumes DC's lights run at their commissioned maximum all night. A dimming schedule already in place would shrink the Phase 0 saving by its own amount.
- Price and grid factor are ASSUMED inputs. Activity uplift is the expected value of the Section 6.4 traffic and pedestrian curves, not DDOT counts.

**Sky model**
- Single scattering only: no Earth curvature, terrain or buildings. That is adequate inside a city and optimistic beyond about 30 km.
- Aerosol load, ground reflectance, luminaire efficacy and the globes' uplight are ASSUMED. The globes' uplight should come from the installed kit's LM-63 file via `nocturne bug`.
- The streetlights' share of DC's sky is Tucson's until DC's own meters calibrate it.

**Optics**
- BUG ratings follow IES TM-15-11 Addendum A, with thresholds checked against their published reproduction. Ratings for procurement should still come from the manufacturer's accredited LM-79 file.
- The trespass check measures light on the outside of the window, before glass and curtains.

**The rest**
- **Night Signal.** A protocol proposal: no owner is bound by it until the District says so.
- **Crash data.** The pilot's power figure uses the District's 2025 crash count. The layer's timestamps are ambiguous between UTC and local time, so the night-time share is given as a range.
- **Places.** The coordinates of the six places are approximate centroids.

## License

MIT. See `LICENSE`.
