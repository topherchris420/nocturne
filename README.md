# Nocturne · VDL-7 reference firmware

Reference implementation of the VDL-7 streetlight edge controller from **VD-DSL-SPEC-001 RevA, *DC Dark-Sky Lighting Engineering Specification*** (Christopher Woodyard, Vers3Dynamics, Oct 2026). It includes the Section 6.2 acceptance suite, the Section 6.3 network night simulation and an interactive operator console.

The spec's central design rule is that **the node, not the CMS, owns the curfew**. Every VDL-7 carries its own astronomical clock, the US DST rule, a signed profile bundle and an event store. A cellular or cloud outage therefore changes only *which events arrive*, never whether the lights dim. This repository is that rule written as code that runs and tests that pass.

> **Status: prototype.** This is a Python reference model of the firmware's behaviour, structured to port to C on a Cortex-M33. It is not certified firmware. The traffic, pedestrian, class-mix and efficacy inputs are the ASSUMED values from Section 6.4.

![Mean output by road class](out/night_profile.png)

```
nocturne-vdl7/
├── vdl7/
│   ├── controller.py     the 1 Hz loop: mode ladder, arbitration, slew, CLO, SAFE clock, alarms, metering
│   ├── clock.py          NOAA solar position, POSIX DST rule, RTC holdover + counter, photocell debounce
│   ├── profiles.py       road-class profiles, phases, floors, tunable-white mix, bundle validation
│   ├── events.py         signed, addressed, sequenced events; monotonic TTLs; anti-replay window
│   ├── cms.py            what the CMS signs and sends: events, overrides, geofences, bundles
│   ├── security.py       Ed25519 signing and key files (HMAC bench signer only on request)
│   ├── driver.py         DALI-2/D4i two-channel driver, 0-10 V, NC relay, failure level, metering model
│   ├── mesh.py           Wi-SUN segment mesh: 12-hop gateway reachability, 3-hop carpet, flood relay
│   ├── spectral.py       LED spectra; Rayleigh, scotopic, Mie, melanopic-DER; LM-79 CSV loader
│   ├── bench.py          single-node bench with a modelled sky and CMS
│   └── cli.py            nocturne trace | spectral | simulate | keygen | bundle
├── sim/run_night.py      400-node night simulation, 8 scenarios, scaled to 75,000 lights
├── tests/                82 acceptance tests: every row of the Section 6.2 table plus extensions
├── console/index.html    the operator console as a standalone page
└── out/                  simulation results: summary.json, report.md, timeseries.csv, charts
```

## Run it

```bash
pip install -e ".[dev]"                 # Python 3.10+; cryptography is the only runtime dependency
pytest -q                               # 82 passed in ~13 s
nocturne trace --road local --offline-at 22:15 --event emergency@00:40:30
nocturne spectral                       # Section 4 metrics; add --spd name=lm79.csv for a measured engine
nocturne simulate --out out             # all scenarios, about 4 min on 2 cores
nocturne keygen --out cms_key.pem       # CMS signing key; prints the public key for the nodes
nocturne bundle --key cms_key.pem --version 2 --out bundle.json
```

Open `console/index.html` in a browser for the interactive console. It runs the same control logic in JavaScript over five streets.

## The control loop (Section 2.4)

`VDL7Controller.tick(mono, dt)` runs once per second and determines everything the node does:

| Step | What the code does | Spec |
|---|---|---|
| 1 Mode | `SAFE` if the RTC isn't trusted; `ONLINE` if backhaul heard ≤ 15 min ago; `MESH` if a gateway path is ≤ 15 min old; otherwise `AUTONOMOUS` | 5.2 |
| 2 Lit | Lit when the sun is below −3° on the node's own clock **or** the photocell reads dark. The photocell can switch lights on early but can never hold them off. In SAFE mode the photocell alone decides | 2.4 |
| 3 Phase | Local civil hour gives the phase, which gives the class base level; DST-aware | 2.2 |
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
7. **Number corrections.** §6.2 says "24 acceptance tests"; the suite has 82. The table's 18 rows become 19 tests, because R-MESH-1/2 is split in two; the rest are extensions. The Section 6.3 and Section 4 figures are reconciled below.

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

## Simulation results (Section 6.3)

`sim/run_night.py` uses the spec's layout: 4 streets × 20 poles per class at 30 m spacing, 400 VDL-7 nodes, run through the night of 13–14 October 2026 in 10-second steps. A modelled CMS sends 15-minute hellos and one signed loop-volume message per segment. Seeded pedestrians walk 4–14 poles. Results are scaled to 75,000 lights by the Section 6.4 class mix.

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

The skyglow waterfall goes 1.00 → −0.326 (dimming) → −0.135 (U0 optics) → −0.052 (warm spectrum) → **0.49**. The saving is 15.1 MWh per night, about **5.5 GWh a year**.

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

- Carpet events between neighbouring nodes are not signed here. The spec's device keys would sign them, but that is out of scope for this model.
- The JavaScript console re-implements the loop. It was checked against the Python by hand: same learned midpoint, same evening levels, static baseline within 0.1 MWh. No automated parity test exists yet.
- Section 3 (optics) is verification of LM-79 data, not firmware. The node only watches tilt.
- The CMS side (TALQ, LwM2M, DTLS) is modelled only by the messages it signs.

## License

MIT. See `LICENSE`.
