# Nocturne · VDL-7 reference firmware

Reference implementation of the VDL-7 edge controller from **VD-DSL-SPEC-001 RevA, *DC Dark-Sky Lighting Engineering Specification*** (Christopher Woodyard, Oct 2026), with the acceptance suite from Section 6.2 and the network night simulation behind Section 6.3.

The design premise of the spec is that **the node, not the CMS, owns the curfew**. Every VDL-7 carries its own astronomical clock, the US DST rule, a signed profile bundle and an event store, so a cellular or cloud outage changes only *which events arrive*, never whether the lights dim. This package is that premise, written down as code that runs and tests that pass.

```
nocturne-vdl7/
├── vdl7/                   reference firmware (pure Python, no runtime deps)
│   ├── clock.py            NOAA solar position, POSIX DST rule, RTC holdover, photocell debounce
│   ├── profiles.py         road-class profiles, phases, floors, tunable-white mix, signed bundle
│   ├── security.py         Ed25519 signing (bench HMAC fallback), canonical encoding
│   ├── events.py           signed events with monotonic TTLs
│   ├── driver.py           DALI-2/D4i 2-channel driver, 0-10 V, NC relay, system-failure level
│   ├── controller.py       the 1 Hz loop: mode ladder, arbitration, slew, CLO, SAFE-mode clock
│   ├── mesh.py             Wi-SUN segment mesh: gateway reachability, 3-hop carpet, flood relay
│   ├── spectral.py         LED spectra, Rayleigh / scotopic / Mie factors, melanopic DER
│   ├── bench.py            single-node bench with a modelled sky and CMS
│   └── cli.py              `nocturne trace | spectral | simulate | bundle`
├── sim/run_night.py        100-node network simulation, 8 scenarios, scaled to 75,000 lights
├── tests/test_controller.py  36 acceptance tests, each named for its requirement ID
└── out/                    simulation outputs: summary.json, report.md, timeseries.csv, PNG charts
```

## Run it

```bash
pip install -e ".[dev]"            # or just: pip install pytest cryptography matplotlib
python -m pytest -q                # 36 passed in ~7 s
python -m vdl7.cli spectral        # Section 4 metrics table
python -m vdl7.cli trace --road local --offline-at 22:15 --event emergency@00:40:30
python -m sim.run_night --out out  # all scenarios, ~3 min, writes charts and summary.json
```

`cryptography` is optional: with it the CMS signs bundles and events with Ed25519 as the spec requires; without it the bench falls back to an HMAC signer that is never valid for a fleet.

## What the controller does, step by step (Section 2.4)

`VDL7Controller.tick(mono, dt)` runs once per second and is the whole of the node's behaviour:

| Step | Code | Spec |
|---|---|---|
| Mode | `SAFE` if the RTC is not trusted; `ONLINE` if backhaul heard ≤ 15 min; `MESH` if a gateway path is ≤ 15 min old; else `AUTONOMOUS` | 5.2 |
| Lit | sun below −3° on the node's own clock **or** photocell dark. The photocell can switch lights on early (storm darkness) but can never hold them off at night. In SAFE the photocell alone decides | 2.4 step 2 |
| Phase | local civil hour → evening / step / curfew / deep / dawn, boundaries in local time so the curfew follows DST | 2.2 |
| Activity | loop volume ÷ design volume while < 15 min old; presence within 90 s or a carpet event sets A = 1 on occupancy classes, A ≥ 0.5 on arterials and collectors | 2.3 |
| Raise | `target = base + (cap − base) × A` | 2.4 step 5 |
| Weather | rain +15 points to the cap; fog and snow nothing, logged | 2.3 |
| Floor | class floor, 60 on the High-Injury Network | 2.2 |
| Emergency | 100 inside an active geofence | 2.3 |
| Override | highest priority wins; only incident-command priority can pull an emergency below 100 | 2.4 step 9 |
| Slew | up 25 %/s, down 1 %/s | 2.4 step 10 |
| CLO | drive = level × (0.86 → 1.00 over 100,000 h) | 2.4 step 11 |
| Output | two DALI channels (white, amber) with the tunable-white mix by phase; NC relay; checkpoint to flash every 60 s | 4.3, 5.2 |

Everything timed is in node-monotonic seconds. Events carry a TTL from the moment they arrive, so a stale emergency expires in SAFE mode without a wall clock (`R-EM-1`).

### SAFE mode without a clock (Section 5.3)

When the RTC is lost, the node estimates the night-hour as
`learned midpoint + (time since dusk − previous night length / 2)`. Dusk is the debounced photocell transition seen this boot; if the node rebooted mid-night, the flash checkpoint written within the last 60 s anchors the estimate instead. The midpoint and night length are re-learned after every clocked night from the astro clock (`learned_night()`), and seeded from it on the first time sync. `R-FS-3` lands the curfew within 10 min after a power cut that zeroes the monotonic clock and loses the RTC; `R-FS-4` lands it within 15 min from a cold boot in daylight with no clock at all.

### Failure below the controller

`LuminaireDriver.commissioned_for(profile)` stores the class's 22:00 level as the DALI system-failure level, and the relay is a normally-closed monostable energised only to switch the light off. A dead node is a slightly over-lit light, never a dark one (`R-FS-5`).

## Acceptance suite

| Requirement | Test | What it checks |
|---|---|---|
| R-CLK-1 | `test_R_CLK_1_dst_rule_matches_iana_2024_2030` | firmware POSIX rule vs the IANA database at every 6-hour step, 10,228 checks |
| R-CLK-2 | `test_R_CLK_2_astronomical_night_at_dc` | known sunrise/sunset for DC in Oct, Dec, Jun within 3 min |
| R-CLK-3 | `test_R_CLK_3_rtc_holdover_trust` | trusted at 1 year, not at 4, never before sync; 7-day supercap |
| R-DIM-1..3 | `test_R_DIM_*` | arterial 60 % at 23:30; every class follows its table; curfew follows DST |
| R-FS-1..5 | `test_R_FS_*` | total outage → AUTONOMOUS; MESH applies an emergency; clock-lost reboot; cold-boot re-anchor; driver fails to 22:00 level |
| R-ADP-1..4 | `test_R_ADP_*` | presence 30→70 in < 2 s, hold, fade; loop volume 75 %; one-slot cache; half activity on arterials |
| R-SAF-1..4 | `test_R_SAF_*` | HIN floor beats rain; fog/snow no boost; photocell veto; storm darkness |
| R-EM-1..2 | `test_R_EM_*` | emergency in SAFE expires on monotonic TTL; override vs emergency priority |
| R-CLO-1 | `test_R_CLO_1_constant_light_output` | 86 % drive new, 100 % at 100,000 h |
| R-MESH-1..3 | `test_R_MESH_*` | 12-hop budget; broken-path isolation; 3-hop carpet |
| R-SEC-1..2 | `test_R_SEC_*` | forged and tampered messages rejected; bundle version monotonic, survives reboot |
| R-TW-1 | `test_R_TW_1_channel_mix_follows_phase_and_presence` | 100:0 → 60:40 → 0:100, white on presence |
| R-SPEC-1 | `test_R_SPEC_1_spectral_metrics_order_and_limits` | CCT within 2 %, Duv within ±0.003, ≤ 7 % below 500 nm at 2200K, melanopic EDI at a window |

## Simulation results

`python -m sim.run_night` drives 100 VDL-7 nodes (five streets, one per road class, twenty poles each on a Wi-SUN chain) through the night of 13–14 October 2026 at 10-second steps, with a modelled CMS sending 15-minute hellos and ATSPM loop volumes, Poisson pedestrians who trip each radar as they walk 4–14 poles, and the fault scenarios from Section 6.3. Results scale to 75,000 lights by the Section 6.4 class mix.

| Scenario | Energy vs today | Delivered light vs today | Skyglow index | MWh / night |
|---|---|---|---|---|
| Today: static 100 %, current CCT | 1.00 | 1.00 | 1.00 | 55.6 |
| Adaptive dimming only | 0.67 | 0.67 | 0.67 | 37.0 |
| + U0 optics | 0.67 | 0.67 | 0.54 | 37.0 |
| + warm spectrum (full Nocturne) | 0.72 | 0.67 | 0.48 | 40.2 |
| Full Nocturne during a 7-hour carrier outage | 0.70 | 0.64 | 0.47 | 38.8 |
| Cloud-dependent nodes in the same outage | 0.94 | 0.94 | 0.94 | 52.3 |
| Full Nocturne with a CAD incident on the local street 00:40-01:40 | 0.73 | 0.67 | 0.49 | 40.6 |
| Full Nocturne with rain 23:00-02:00 | 0.77 | 0.70 | 0.51 | 42.6 |

Skyglow waterfall (upward flux × Rayleigh, today = 1.00): Today 1.00 → Adaptive dimming 0.67 (-0.330) → U0 optics 0.54 (-0.134) → Warm spectrum 0.48 (-0.052). Annual saving against the static baseline: about 5.61 GWh.

These land within a few points of the spec's own Table 6.3 (dimming 0.65 / 0.65, full Nocturne 0.70 / 0.65, outage 0.68 / 0.63, waterfall −0.35 / −0.12 / −0.04 → 0.49) from independently written traffic and pedestrian models, which is the point: the numbers follow from the profile table and the controller logic, not from tuning.

Charts in `out/`: `night_profile.png` (mean output by class), `outage_comparison.png` (VDL-7 in AUTONOMOUS mode vs a cloud-dependent node that fails bright), `skyglow_waterfall.png`.

## Spectral model

`vdl7/spectral.py` builds parametric white-LED spectra (450 nm pump + two phosphor bands) fitted to the Planckian locus, PC-Amber (600 nm phosphor, 0.4 % residual pump) and narrow-band amber, then computes per photopic lumen:

- `G_R = ∫S λ⁻⁴ / ∫S V` — physical Rayleigh scatter,
- `G_scot = ∫S λ⁻⁴ V′ / ∫S V` — skyglow as the rod-dominated dark-adapted eye sees it,
- the Mie λ⁻¹·³ factor that dominates near the city and is almost colour-blind,
- `mel-DER` per CIE S 026 (D65 = 1).

Colour-matching functions are the Wyman–Sloan–Shirley multi-lobe fit; V′(λ) is the CIE 1951 scotopic table; the melanopic template is a 480 nm Govardovskii nomogram behind a 32-year-old lens (peak 484 nm). Absolute error a few percent, less in ratios.

## Porting notes

The loop allocates nothing but its output record, reads no wall clock outside `tick`, and keeps every timer in monotonic seconds, so the structure maps onto a Cortex-M33 directly: `clock.py` becomes the NOAA routine plus a POSIX rule, `events.py` a fixed-size ring of 64 records, `controller.py` the 1 Hz task, `mesh.py` the Wi-SUN FAN callbacks. Signing uses Ed25519 over canonical JSON; on the MCU the same bytes verify against the public key in the secure element.

## Open items carried from the spec

- Replay within an event's TTL is not prevented (a nonce cache or issued-time window at the CMS would close it).
- The installed RMCS node's lost-comms behaviour, the class mix, design wattages, efficacies and traffic curves are the spec's ASSUMED values (Section 6.4); the simulation reads them from `sim/run_night.py` constants and should be re-run against the DDOT inventory and ATSPM data.
- Luminaire optics (Section 3) are verification rules on LM-79 data, not firmware; the VDL-7 only watches tilt.
