# Cutting light pollution with technology: a proposal

[Back to the README](../README.md)

This proposal sets out the hardware, software, sensors, materials and data systems that can cut skyglow, glare, light trespass and harm to wildlife while keeping streets safe, sites secure and budgets intact. It is written from five seats at once:

- **Astrophysics:** where skyglow comes from.
- **Lighting engineering:** what luminaires and controls can do.
- **Urban planning:** where light is needed, and when.
- **Materials science:** optics, phosphors, glazing and surfaces.
- **Systems engineering:** how each solution fails, and how its results are verified.

For each technology the proposal gives what it is, how it reduces light pollution, how ready it is, what it costs and what stands in the way, how much it could do, and what can go wrong. A prioritised roadmap closes the page.

**How to read the numbers**

- **DC figures** come from this repository's models, run on DDOT's own streetlight inventory. Each names the command that reproduces it.
- **Other figures** cite their source. Costs are indicative US dollars for the year given. ESTIMATE marks a figure for which no public source was found. Get local quotes before budgeting.
- **Readiness** uses technology readiness levels (TRL):
  - *commercial* (TRL 9): bought and installed at scale;
  - *early commercial* (TRL 7–8): on sale, few large deployments;
  - *pilot* (TRL 5–6): demonstrated in the field;
  - *research* (TRL 4 or lower).

## Contents

0. [The physics that sets the priorities](#0-the-physics-that-sets-the-priorities)
1. [Individual fixtures and buildings](#1-individual-fixtures-and-buildings)
2. [Street and municipal lighting](#2-street-and-municipal-lighting)
3. [Commercial, industrial and sports facilities](#3-commercial-industrial-and-sports-facilities)
4. [Regional and satellite monitoring and control](#4-regional-and-satellite-monitoring-and-control)
5. [Roadmap: what to pursue first](#5-roadmap-what-to-pursue-first)
6. [Sources](#6-sources)

## At a glance

⟦GLANCE⟧

## 0. The physics that sets the priorities

The artificial brightness of the sky over a place is a sum over every light source:

> **skyglow** = Σ over sources of **lumens** × **share of the night on** × (**uplight** + **reflectance** × **downlight**) × **spectral weight** × **distance kernel**, amplified by cloud and snow.

This is the single-scattering model in `vdl7/skyglow.py`. Every technology on this page moves one or more of its factors:

| Factor | What moves it |
|---|---|
| Lumens installed | right-sized designs, constant-light-output drivers, lumen budgets |
| Share of the night on | schedules, dimming, presence sensing, curfew signals, booking-linked sports controls |
| Uplight | full-cutoff optics, retrofit shields and reflectors, fixed aiming, blinds and glazing on lit windows |
| Reflectance | surface materials; optics that put light only where the task is |
| Spectral weight | warm-white, amber and tunable LEDs |
| Distance kernel | *where* light is cut: near the places to protect, and the near-horizontal light that travels furthest |

The factors multiply, so measures stack: a luminaire dimmed by half, fully shielded and warmer is cut three times over.

Three facts set the priorities.

1. **Streetlights are a minority of the sky.**
   - **Tucson:** municipal streetlights were about 14 % of the emissions behind the city's skyglow (Barentine et al. 2020), and 13 % of the upward light seen from orbit after midnight (Kyba et al. 2021).
   - **Flagstaff:** a source-by-source inventory found commercial and industrial lighting at 62 % of the city's upward light when its sports fields were dark, residential at 14 % and roadways at 12 %. Sports lighting was about a third of all upward light while it was on (Luginbuhl et al. 2009).
   - **Berlin:** in an aerial survey, light associated with streets (streetlights, headlights and roadside advertising together) was 31.6 % of the light directed up (Kuechly et al. 2012).
2. **Timing is fast and reversible; optics and spectrum are permanent.** Dimming can start next week on controllers a city already owns. Shielding and spectrum arrive with the replacement cycle, so every replacement must carry them.
3. **Near-horizontal light travels furthest.** ⟦A7⟧ Lit windows, unshielded wall packs and sideways floodlights emit exactly there.

### What that means for DC

Nocturne's sky model carries DC's real streetlight grid to six places where people look up. Everything that is not a streetlight is taken from the Tucson share (streetlights 15 % of artificial light) until DC has its own sky meters. Each technology package after 01:00:

| Package, after 01:00 | Rock Creek Park | National Mall |
|---|---|---|
| Today | 17.90 mag/arcsec², 225 stars overhead | 16.88, 85 stars |
| Nocturne's full streetlight programme (adaptive, shielded globes, warm spectrum) | 17.99, 246 | 16.98, 94 |
| The rest of the city's lighting cut 30 % after a 23:00 curfew (the Model Lighting Ordinance's minimum) | 18.21, 301 | 17.20, 116 |
| The rest cut 50 % after curfew | 18.48, 387 | 17.47, 151 |
| The rest fully shielded (half its skyglow, at every hour) | 18.48, 387 | 17.47, 151 |
| **All three:** streetlight programme, 50 % curfew and full shielding | **19.24, 759** | **18.28, 321** |
| For the Milky Way to show overhead (about 20.3 mag/arcsec²) | 91 % less artificial light | 96 % less |

Higher mag/arcsec² is a darker sky. Reproduce with `python tools/sky_packages.py`; the [sources](#6-sources) cover the Milky Way threshold (Falchi et al. 2016) and the shielding estimate (Luginbuhl et al. 2009).

- **The prior moves the absolute values, not the order.** With streetlights at 10–20 % of the artificial light (`--share 0.10` to `0.20`), "all three" gives Rock Creek Park 545–935 stars after 01:00, and the Milky Way needs an 88–94 % cut.
- **Early evening needs different tools.** A 23:00 curfew does nothing at 21:00, when most people are out; there, only shielding and sensing that dims empty sites move the sky (Rock Creek Park: 225 stars → 387 with shielding).
- **No single device solves it.** Streetlight technology is necessary and ready, but most of the light comes from owners the city does not control. Bringing the Milky Way back over a city the size of DC takes roughly a tenfold cut, reachable only by stacking curfews, shielding, sensing and spectrum across every owner, and by verifying the result.

## 1. Individual fixtures and buildings

### 1.1 Full-cutoff precision optics and retrofit shields

**What it is.** LED luminaires whose optics put no light above the horizontal: flat glass, total-internal-reflection lenses or specular reflectors. That is a TM-15 uplight rating of U0, alongside low backlight (B) and glare (G) ratings.
- **For existing decorative globes and acorns:** internal top reflectors and baffles.
- **Toward homes:** house-side shields that cut backlight.
- **In the field:** fixed mountings, and a tilt sensor in the controller that catches a luminaire knocked out of level.

**How it cuts light pollution.** It removes direct uplight, including the near-horizontal part that dominates distant skyglow, and the same BUG limits cap light trespass and glare. Light reflected from the lit ground is unchanged.

**Readiness.**
- New full-cutoff luminaires: commercial (TRL 9).
- Reflector and baffle retrofits for globes: early commercial (TRL 8), specific to each luminaire model.

**Cost and barriers.** ⟦A-cost⟧ The barriers are historic-district taste for glowing globes, a replacement cycle of one to two decades, and aiming that drifts in the field.

**Impact.**
- **Flagstaff:** shielding all of the city's lighting would roughly halve its sky glow (Luginbuhl et al. 2009).
- **DC streetlights:** top reflectors in the post-top globes, which carry 27 % of the streetlights' power, cut the streetlights' annual sky index by a further 13 % once adaptive control is running (0.669 → 0.581, `nocturne business-case`). In the evening they remove a further 6–24 points of the streetlight sky at the six places (`nocturne sky`).
- **One example luminaire:** a globe sending 15 % of its light upward rates B2-U4-G2; the same globe with a top reflector rates B2-U0-G2 (`nocturne bug examples/ies/synthetic-globe-4000lm-ulr15.ies`, then `…-reflector-u0.ies`).

**Trade-offs and failure modes.**
- Less light on faces and facades, which can mean closer spacing or a wider distribution.
- A U0 luminaire can still glare, so check G as well as U.
- Bright pavement still reflects light upward.
- A tilted or re-aimed luminaire loses its rating; the Model Lighting Ordinance bars adjustable mountings for this reason (IDA & IES 2011).

### 1.2 Spectrum: warm white, amber and tunable

**What it is.** LED engines with less short-wavelength light:
- 2200 K white;
- phosphor-converted (PC) amber: a blue pump almost wholly converted by an amber phosphor;
- narrow-band amber: direct-emitting AlInGaP, near 590 nm;
- two-channel tunable luminaires that run white in the evening and amber after curfew (VDL-7's tunable-white mode).

**How it cuts light pollution.**
- Molecular (Rayleigh) scattering scales as λ⁻⁴.
- The dark-adapted eye, and so the skyglow it sees, peaks at 507 nm; the circadian (melanopic) response peaks near 490 nm.
- Many insects are drawn to short wavelengths.

Per photopic lumen, from `nocturne spectral` (4000 K = 1.00):

| Spectrum | Skyglow seen by the dark-adapted eye | Aerosol (Mie) scatter | Melanopic DER |
|---|---|---|---|
| 4000 K | 1.00 | 1.00 | 0.61 |
| 3000 K | 0.77 | 0.95 | 0.45 |
| 2700 K | 0.68 | 0.94 | 0.39 |
| 2200 K | 0.47 | 0.91 | 0.26 |
| PC-amber | 0.17 | 0.73 | 0.06 |
| Narrow-band amber | 0.07 | 0.59 | 0.01 |

Close to the city, aerosol scattering is nearly colour-blind, so the gain there is smaller than the molecular figures suggest. It grows with distance.

**Readiness.**
- 2200 K and PC-amber: commercial.
- Narrow-band amber: commercial, mostly in wildlife lighting ⟦A3⟧.
- Tunable white-to-amber roadway luminaires: early commercial.

**Cost and barriers.** ⟦A4⟧ The barriers are colour rendering, public acceptance of amber, and procurement specifications that still ask for 3000–4000 K.

**Impact.**
- **DC streetlights:** at replacement, the Section 4 spectrum (2700 K arterials; 2200 K collectors, local streets and alleys; PC-amber at park edges) cuts the streetlights' annual sky index a further 6 % (0.581 → 0.545) for 5 % more energy (10.9 → 11.5 GWh, `nocturne business-case`).
- **Wildlife:** ⟦B8-B10⟧

**Trade-offs and failure modes.**
- **Energy:** the efficacy penalty works against the energy goal, so pair amber with dimming.
- **Vision:** at low light levels, short-wavelength-rich light helps peripheral detection (CIE 191:2010), so a warmer spectrum may need slightly more photopic light for the same off-axis visibility.
- **Birds:** the evidence on colour is mixed, and intensity matters more ([evidence review](EVIDENCE.md) §5).
- **Colour rendering:** amber makes colours hard to tell apart, which suits habitat edges and paths, not shopping streets.

### 1.3 Controls in the luminaire: dimmable drivers, clocks, vacancy sensors and constant light output

**What it is.** Four controls on every new outdoor luminaire:
- a dimmable driver (DALI-2 with D4i data, or 0–10 V) and a standard controller socket (Zhaga Book 18, or the ANSI C136.41 seven-pin receptacle);
- an astronomical time switch, rather than a photocell alone;
- a passive-infrared or microwave vacancy sensor;
- constant-light-output (CLO) programming, which starts the LEDs below full drive and raises it as they age.

**How it cuts light pollution.**
- Fewer hours at full output.
- A failed photocell can no longer burn a light all day.
- No initial over-lighting: designers size luminaires for their end-of-life output, so without CLO a new installation delivers more light than the design needs.

**Readiness.** Commercial.

**Cost and barriers.** ⟦A10/B5/C-sensor⟧ The barrier is that cheap residential and small-commercial fixtures still ship as dusk-to-dawn units with no dimming or sensing.

**Impact.**
- **CLO:** VDL-7's profile (86 % drive when new, rising to 100 % at 100,000 h) uses about 7 % less energy over the luminaire's life, and up to 14 % less light in its first years (`vdl7/profiles.py`). ⟦B5⟧
- **Codes:** ⟦C1-C2⟧
- ⟦A10⟧

**Trade-offs and failure modes.**
- False triggers from foliage, animals or passing cars bring light on needlessly.
- A failed sensor must fail to a safe level, neither off nor full.
- Lights that switch abruptly annoy neighbours; fade times matter.

### 1.4 Building envelopes: interior light kept inside

**What it is.**
- After-hours sweeps of interior lighting: vacancy sensors and scheduled shut-off, already required by energy codes such as ASHRAE 90.1.
- Perimeter-zone switching.
- Motorised blackout blinds, or electrochromic glazing.

All of it is run by the building automation system on a schedule tied to the city's curfew and migration feed (4.4).

**How it cuts light pollution.** Lit windows emit close to the horizontal, which reaches distant skies, and at the heights where migrating birds fly, which draws them into collisions.

**Readiness.**
- Vacancy sensors, building automation schedules and motorised blinds: commercial.
- Electrochromic glazing: commercial, at a premium.
- A signed public feed driving those schedules: prototype (`vdl7/nightsignal.py`).

**Cost and barriers.** A schedule change in an existing building automation system needs no hardware. ⟦A2⟧ The barriers are night cleaning crews and late workers, and tenant control of their own floors.

**Impact.** ⟦C6⟧ When the lights go off, birds disperse within minutes (Van Doren et al. 2017).

**Trade-offs and failure modes.**
- Occupants override blinds.
- Electrochromic glass takes minutes to tint, and reduces transmitted light rather than eliminating it ⟦A2-range⟧.
- A schedule that fails must fail to "off after hours", not "on".

### 1.5 Materials that do the job of light

**What it is.**
- **Retroreflective sign sheeting:** microprismatic sheeting (ASTM D4956 Types IX–XI) returns headlight to the driver, so overhead guide signs need no luminaires of their own.
- **Photoluminescent markings:** strontium-aluminate paint that charges by day and glows at night.
- **Surfaces chosen for the lighting method:** dark or bright paving and facades, matched to how the space is lit.

**How it cuts light pollution.** Sheeting removes luminaires altogether. Photoluminescent paint replaces low-level wayfinding light. Surface choice sets how much of the downward light is reflected up ⟦A9⟧.
- Where a road is designed to a *luminance* target, a brighter surface lets the luminaires deliver less light for the same visibility.
- Where a space is designed to an *illuminance* target, a brighter surface simply reflects more into the sky.
- The same conflict applies to high-albedo "cool" pavements and roofs installed against urban heat.

**Readiness.**
- Retroreflective sheeting: commercial.
- Photoluminescent road markings: pilot ⟦A5⟧.
- Surface selection: a design choice, available now.

**Cost and barriers.** ⟦A6⟧ DC's inventory lists 131 overhead-guide-sign luminaires, kept static today (`data/dc/fleet.json`); with high-performance sheeting they are candidates for removal.

**Impact.** ⟦A6-impact⟧

**Trade-offs and failure modes.**
- Retroreflection serves only someone beside a light source, such as a driver, not a pedestrian.
- Photoluminescent glow is faint and fades over hours ⟦A5-fail⟧.

## 2. Street and municipal lighting

### 2.1 Time-of-night dimming on the controllers a city already has

**What it is.** Software. The central management system (CMS) pushes a time-of-night programme to the networked controllers already on the poles:
- one programme per road class, stepping down at fixed local times after the evening peak and back up before dawn;
- dusk and dawn from each node's own astronomical clock;
- each class's minimum level held, and High-Injury Network segments never below 60 %.

`nocturne schedule` exports these programmes, and `nocturne business-case` integrates exactly them.

**How it cuts light pollution.** It removes full output from the hours when the fewest people are out.

**Readiness.** Commercial (TRL 9) wherever networked nodes exist. DC's are already installed: 97 % of its 72,512 active streetlights are LED, and 69,550 of the 72,068 dimmable lights carry a registered networked node ([inventory notes](../data/dc/README.md)).

**Cost and barriers.** The cost is integration and policy, not hardware. In the business case, Phase 0 pays back within three years if integration costs less than $1.92 million. The barriers are:
- translating the programmes into the CMS vendor's import format;
- confirming, under the streetlight contract, who may change schedules;
- public concern about safety.

**Impact in DC (2027, `nocturne business-case`).**
- Energy falls from 16.4 to 11.5 GWh a year (−30 %).
- That saves about $641,000 and 1,480 t of CO₂ a year, at an ASSUMED $0.13/kWh and 0.30 t/MWh.
- The streetlights' contribution to the sky falls 30 % over the year, and 44–46 % after 01:00 at the six places (`nocturne sky`).

**Trade-offs and failure modes.**
- If a city already dims, its saving is smaller.
- People may feel less safe. The evidence is reassuring: across 62 local authorities in England and Wales, switch-off, part-night lighting and dimming showed little evidence of harm to night-time collisions or crime (Steinbach et al. 2015). Nocturne's rollout is still randomised, with a brake that pauses it if night-time crashes rise (`nocturne brake`).
- A controller that loses its network must not revert to full output (see 2.3).

### 2.2 Presence-adaptive lighting

**What it is.** A radar or passive-infrared sensor at each pole detects pedestrians, cyclists and vehicles.
- The node raises its own light, and over a local mesh the next three poles ahead (a "light carpet"), within two seconds, then fades back.
- Arterials follow live loop-detector volumes ⟦B6⟧.
- Firmware floors hold every road class at or above its IES RP-8 level, whatever the sensors or a signed message say.

The VDL-7 controller in `vdl7/controller.py` models all of this.

**How it cuts light pollution.** Empty streets can go darker than any fixed schedule would dare, above all local streets, alleys and park edges.

**Readiness.** Sensors and adaptive controllers are commercial, with field trials behind them ⟦B4⟧. The VDL-7 controller in this repository is a reference model (prototype).

**Cost and barriers.** ⟦B3⟧ On energy alone it does not pay in DC. Once Phase 0 is running, a node would have to cost less than about $11 per pole to repay itself in ten years, or about $14 on local streets (`nocturne business-case`). Its case is darkness where it matters most and light where people are. Deploy it first at park and river edges and on residential streets that ask for it.

**Impact in DC, beyond Phase 0.**
- Energy falls from 0.700 to 0.663 of today.
- Mean level falls on local streets from 58 to 52 %, in alleys from 55 to 42 % and on park edges from 52 to 32 %.
- After 01:00, the streetlights' contribution to the sky at the six places falls 48–56 %, against 44–46 % for Phase 0.

**Trade-offs and failure modes.**
- Missed detections (dark clothing, a blocked sensor, speed at the edge of range) must fail toward light, which is why the base level never drops below the class floor.
- False triggers from foliage or animals erode the saving.
- Light that follows people can feel like surveillance. Radar and passive infrared do not form images; cameras do, and raise privacy questions.
- Every message that can raise or lower light must be signed and protected against replay (`vdl7/security.py`).

### 2.3 Controllers that keep the schedule when the network fails

**What it is.** The schedule lives on the node itself:
- an astronomical clock and the city's daylight-saving rule;
- signed profile bundles in two flash banks;
- a fallback that learns the night's length and midpoint from its photocell, in case the clock is ever lost.

A cut network changes which new messages arrive, not what the light does.

**How it cuts light pollution.** It prevents "fail bright", where controllers that depend on the cloud revert to full output during an outage.

**Readiness.** Prototype. The VDL-7 reference firmware in this repository carries the design and its acceptance tests. Commercial controllers keep local schedules to differing degrees, so the fallback behaviour belongs in procurement specifications.

**Cost and barriers.** Firmware, plus a real-time clock with holdover (the spec's supercapacitor). The barrier is that procurement rarely specifies outage behaviour.

**Impact.** In Nocturne's 400-node night simulation, a seven-hour carrier outage left cloud-dependent control on the same luminaires delivering 0.95 of today's light, against 0.65 for local autonomy: 30 points of light and 32 points of energy (`nocturne simulate`, [engineering reference](ENGINEERING.md)).

**Trade-offs and failure modes.**
- Firmware complexity and key management.
- Without a clock, accuracy drifts by roughly 1–2 minutes per day of outage near the equinoxes until the next time sync.

### 2.4 Output that follows weather and surface

**What it is.** Road-weather sensors, or a camera calibrated as a luminance meter, adjust output to hold visibility rather than a fixed flux:
- raise on wet roads, which lose diffuse luminance;
- give no boost in fog, where more light mostly adds veiling glare;
- lower when snow brightens the scene.

VDL-7 already applies the first two rules. Lowering on snow is proposed here.

**How it cuts light pollution.** Overcast skies multiply urban skyglow ⟦A8⟧ and snow raises ground reflectance, so fixed output does the most harm exactly when the scene needs least light.

**Readiness.** Weather-dependent lighting classes are recognised in road-lighting standards ⟦B6⟧. Closed-loop luminance control is at pilot stage.

**Cost and barriers.** Weather data from existing road-weather stations or forecasts costs nothing per pole. Luminance cameras need calibration, and the barrier is validating that the loop keeps visibility.

**Impact.** Not yet modelled in Nocturne. ⟦A8-impact⟧

**Trade-offs and failure modes.** Lenses foul and calibration drifts, so the loop must fall back to the base programme, never below the class floor.

### 2.5 Guidance instead of illumination where lighting is not warranted

**What it is.** On park drives, rural roads and river paths that do not need continuous light, delineation does the job:
- raised retroreflective pavement markers, solar LED road studs and reflective edge posts;
- on the vehicle, adaptive driving beam (ADB) headlamps, which keep the high beam on except where it would dazzle someone. They have been legal on new US vehicles since NHTSA amended FMVSS No. 108 in February 2022.

**How it cuts light pollution.** There is no fixed light on those segments at all.

**Readiness.** Commercial.

**Cost and barriers.** ⟦studs⟧ The barrier is a segment-by-segment risk assessment against crash data.

**Impact.** All of that lighting's skyglow and energy, and a dark gap in wildlife corridors.

**Trade-offs and failure modes.** It serves drivers, not pedestrians or cyclists. Snowploughs damage raised markers in snowy climates.

## 3. Commercial, industrial and sports facilities

These are the owners behind most of a city's upward light (section 0). For every one of them the technology already exists; what is missing is a reason to turn it on, and a clock to follow (4.4).

### 3.1 Sports lighting: precision optics and controls tied to bookings

**What it is.**
- LED sports floodlights with precision optics and integral visors or louvres that cut light above the field and beyond its edges.
- Aiming designed in software to the field's boundary.
- Instant on and off, with dimming: a training level and a match level.
- Control tied to the booking system, so the lights come on for a booked slot and go off within minutes of its end, with remote monitoring.

**How it cuts light pollution.** Sports lighting is among the most intense lighting a city has: in Flagstaff it was about a third of all upward light while it was on (Luginbuhl et al. 2009). The optics cut spill and uplight, the controls cut hours, and dimming cuts light for training.

**Readiness.** Commercial.

**Cost and barriers.** ⟦C3⟧

**Impact.** ⟦C3-impact⟧

**Trade-offs and failure modes.**
- Broadcast television needs high vertical light on players, which means more glare.
- Balls in high flight leave the lit volume, so baseball and cricket need some light above the field.
- A booking-linked controller must default to off, with a manual override that times out.

### 3.2 Car parks and area lighting: lumen budgets and occupancy control

**What it is.**
- Full-cutoff LED area luminaires, designed to a lumen budget per area of paving. The Model Lighting Ordinance allows 0.5, 1.25, 2.5, 5.0 and 7.5 lumens per square foot of hardscape in lighting zones 0–4, and no light above the horizontal from car-park luminaires (IDA & IES 2011).
- Bi-level occupancy sensors that drop each pole to a low level while the area is empty.
- An after-hours reduction of at least 30 %, or switch-off.

**How it cuts light pollution.** The budget caps lumens, sensing cuts hours, and cutoff optics remove uplight.

**Readiness.** Commercial, and increasingly required by energy codes ⟦C1-C2⟧.

**Cost and barriers.** ⟦C9-cost⟧ The barriers are owners' fear that an empty, dim car park invites crime, and camera systems that need light (see 3.5).

**Impact.** ⟦C9⟧

**Trade-offs and failure modes.**
- Sensor coverage gaps at the edges of large lots.
- Re-brightening must be fast enough that a driver never enters a dark lot.

Software can check a permit application's photometric files for both the lumen budget and the BUG ratings automatically, as `nocturne bug` does for one luminaire.

### 3.3 Signs and media facades: brightness that follows the night

**What it is.**
- Digital billboards and electronic signs with photometers that hold brightness a fixed margin above ambient light ⟦C4⟧, under a night-time luminance cap.
- Switch-off or deep dimming after the business closes, on the city's curfew feed.
- Static signs lit from above and aimed down, or internally lit with dark backgrounds.

**How it cuts light pollution.** At night ambient light is low, so a sign that tracks it runs at a small fraction of its daytime luminance, and a curfew removes it after close.

**Readiness.** Commercial: ambient dimming is built into current digital billboards.

**Cost and barriers.** Little hardware beyond what current signs carry. The barrier is advertising revenue tied to hours lit.

**Impact.** ⟦C4-impact⟧

**Trade-offs and failure modes.**
- A failed ambient sensor can lock a sign at full daytime brightness. Specify a fail-dim default and a hard night-time cap in the controller.

### 3.4 Facades and monuments: light kept on the surface

**What it is.**
- Narrow-beam projectors with framing shutters or gobos that put light only on the facade.
- Lighting from the top down where the architecture allows.
- Dimming and curfew through the building automation system, with whole-night switch-off on forecast heavy-migration nights (4.4).

**How it cuts light pollution.** A wide flood aimed up a facade sends much of its light past the building into the sky; a framed projector keeps it on the stone.

**Readiness.** Commercial.

**Cost and barriers.** Framing projectors cost more than floods. The barriers are heritage and tourism expectations, and owners such as federal agencies that a city cannot compel.

**Impact.** Switching off an intense installation releases trapped migrating birds within minutes (Van Doren et al. 2017). ⟦C6⟧

**Trade-offs and failure modes.** Top-down lighting is not always possible on historic buildings, and a precisely framed beam drifts if the projector is knocked.

### 3.5 Industrial sites, ports and logistics: zoned light, and security without floodlight

**What it is.**
- Yards zoned and lit only where vehicles or staff are, triggered by occupancy sensors, gate events or vehicle telematics.
- Flat-glass floodlights mounted level, with zero tilt.
- Thermal and near-infrared cameras with video analytics for perimeter security, bringing visible light on only when an alarm needs it ⟦C8⟧.

**How it cuts light pollution.** It replaces all-night security floodlighting, among the most upward-leaking lighting there is, with light on demand.

**Readiness.** Commercial.

**Cost and barriers.** ⟦C8-cost⟧ The barriers are insurers' and security contractors' habit of specifying light, and work zones that need light during operations.

**Impact.** ⟦C8-impact⟧

**Trade-offs and failure modes.**
- Thermal cameras cost more than visible-light ones.
- Near-infrared illuminators at 850 nm glow faintly red; 940 nm is invisible but shorter-ranged.
- Workers need light where they work, so zoning must follow operations, not just the clock.

### 3.6 Greenhouses: blackout screens

**What it is.** Light-tight screens (blackout or aluminised fabrics) drawn across greenhouse roofs and walls at night while supplementary grow lights are on, with sealed gaps and side walls.

**How it cuts light pollution.** It contains the light physically. In greenhouse regions, horticultural lighting can outshine the towns around it ⟦C5⟧.

**Readiness.** Commercial, and mandatory in some places ⟦C5⟧.

**Cost and barriers.** ⟦C5-cost⟧

**Impact.** ⟦C5-impact⟧

**Trade-offs and failure modes.** Heat and humidity build up under closed screens, and a torn screen or open gap leaks light.

## 4. Regional and satellite monitoring and control

### 4.1 Satellites that find where light is growing

**What it is.** Night-time radiance from orbit, at two scales:
- **City-wide, every night:** the VIIRS Day/Night Band ⟦D1⟧, and NASA's Black Marble products built from it ⟦D2⟧.
- **Street-level and in colour:** SDGSAT-1's Glimmer imager ⟦D3⟧, commercial night imagery ⟦D4⟧, and astronaut photographs from the International Space Station.

Change detection on these images flags new or brightened sources for inspection, tracks trends, and helps build the inventory of private lighting that no city database holds.

**How it cuts light pollution.** Indirectly: it shows where light is growing, aims inspections and retrofits, and checks that a programme happened.

**Readiness.** VIIRS and Black Marble are operational and free. ⟦D3-ready⟧

**Cost and barriers.** The data are free or ⟦D4-cost⟧; the cost is analysts' time. The barrier is that most lighting rules have no satellite-based enforcement path.

**Impact.** It is the only way to see a whole region at once. ⟦D5-D6⟧

**Trade-offs and failure modes.**
- ⟦D1-blue⟧ A city converting to white LEDs can therefore look darker from orbit while its sky gets brighter.
- Satellites see mostly light leaving steeply upward, whereas distant skyglow is driven by near-horizontal light.
- One overpass time, coarse pixels, and interference from cloud, moonlight and snow.

### 4.2 Ground sensor networks and the curfew-step method

**What it is.**
- **Stations:** low-cost photometers (Unihedron SQM-LU-DL, the STARS4ALL TESS-W) logging zenith brightness every few minutes at fixed sites, plus all-sky cameras for the whole hemisphere and its colour.
- **Method:** `nocturne verify` keeps readings taken in full darkness with the Moon down and steady skies. It then measures, night by night, the step in brightness across the 23:00 curfew, before and after go-live.

**How it cuts light pollution.** It closes the loop:
- it replaces the borrowed Tucson share with DC's own (`nocturne sky --measured rock-creek=18.4`);
- it shows whether a programme worked;
- it flags backsliding.

**Readiness.** The instruments are commercial. The curfew-step method in `vdl7/observe.py` is a prototype, tested on a season of synthetic readings with clouds and moonlight.

**Cost and barriers.** ⟦D7⟧ The barrier is upkeep: a dirty window, a dead battery or a moved mount silently corrupts a record.

**Impact.** Weather, season and aerosol cancel within a night. The curfew step therefore shows a 0.05 mag/arcsec² change in a single season, where a naive before-and-after comparison of the late-night sky is about ten times noisier ([playbook](PLAYBOOK.md)).

**Trade-offs and failure modes.**
- Sensors drift and age, so they need cross-calibration.
- A zenith-only photometer misses the horizon glow that matters to wildlife and to distant observatories.

### 4.3 A skyglow digital twin to aim the money

**What it is.** A radiative-transfer model of the city's light inventory and its atmosphere, calibrated against the ground network. It ranks every block's possible retrofits by the sky they would regain at protected places per dollar, and tests a policy before it is adopted. Nocturne's model is single scattering on DC's real grid; research models ⟦D10⟧ add multiple scattering, terrain and obstacles.

**How it cuts light pollution.** The distance kernel falls steeply, so the same retrofit is worth far more near a park than across town. The twin spends the budget where it buys the most sky.

**Readiness.** Prototype (`vdl7/skyglow.py`); research models are mature but need expert users.

**Cost and barriers.** Software and staff time. The barrier is the inventory: cities rarely hold one for private lighting, which satellites (4.1) and permit files can fill.

**Impact.** In DC, `nocturne sky --retrofits 10` puts first a cell near Anacostia Park whose 5 kW of post-top globes, once fixed, remove 2.5 % of the streetlight sky there.

**Trade-offs and failure modes.** Absolute brightness depends on assumed aerosol and reflectance. Beyond about 30 km, single scattering without Earth curvature or terrain is optimistic. Calibrate against measurements and rank by *relative* gain.

### 4.4 A machine-readable curfew and migration signal

**What it is.** One public feed, signed by the city each evening, as JSON and as a calendar (`nocturne signal`). It carries:
- dusk and dawn, and the Moon;
- the moment each phase begins, resolved through local daylight-saving time;
- whether a heavy bird-migration night is forecast ⟦C7⟧;
- for each kind of non-street lighting (facades, signs, empty office floors, car parks, sports fields), the recommended output in each phase.

Building automation, sign controllers, sports-field controllers and smart-home hubs subscribe and act on it, and the signature lets them trust it.

**How it cuts light pollution.** It synchronises every owner's existing controls with the curfew and with migration nights, at almost no marginal cost. Where curfew hours become law, as in France ⟦D11⟧, it becomes the compliance clock.

**Readiness.** Prototype (`vdl7/nightsignal.py`). The automation it drives is commercial, and BirdCast forecasts are operational.

**Cost and barriers.** Publishing costs almost nothing. For a subscriber it is one schedule integration in the building automation or sign controller that is already there. The barrier is participation, which is voluntary until the law says otherwise.

**Impact.** This is the lever the DC table at the top turns. With the rest of the city's lighting halved after 23:00, Rock Creek Park after 01:00 goes from 246 stars (streetlight programme alone) to 454. Even the ordinance-minimum 30 % cut beats the whole streetlight programme.

**Trade-offs and failure modes.**
- If the feed is down, a subscriber must keep its last schedule rather than revert to all-on.
- An unsigned feed could be spoofed to switch a district's lights.
- Compliance is invisible without measurement (4.1, 4.2).

### 4.5 Obstruction lighting that waits for aircraft

**What it is.** Aircraft detection lighting systems (ADLS) on wind turbines and tall towers. A dedicated radar, or a transponder receiver, detects approaching aircraft, and the obstruction lights stay dark until one is near. On communication towers, flashing-only lighting replaces steady-burning red lights.

**How it cuts light pollution.** Removes most of the red blinking that dominates rural night horizons, and the steady lights that draw migrating birds into towers.

**Readiness.** ⟦D8⟧

**Cost and barriers.** ⟦D8-cost⟧

**Impact.** ⟦D8-impact⟧ ⟦D9⟧

**Trade-offs and failure modes.** A radar fault must turn the lights on, not off. Coverage needs certification at each site, and the fixed cost hits small sites hardest.

## 5. Roadmap: what to pursue first

Ranked by how much sky and energy each buys per dollar and per month, using technology that is ready now.

1. **Schedule dimming on the networked streetlight controllers already installed (2.1).**
   - Weeks of work, no hardware.
   - In DC: 30 % less streetlight energy, about $641,000 a year, and 44–46 % less streetlight skyglow after 01:00.
   - The savings fund the rest, and the randomised rollout answers the safety question with data.
2. **Curfew and occupancy automation for everyone else's lighting, driven by one signed city feed (4.4, with 1.3, 1.4 and section 3).**
   - This is the largest lever on the sky, because most of the light is not streetlights.
   - It uses controls owners already have: building automation schedules, sign controllers with ambient sensors, car-park occupancy sensors and sports booking systems.
   - In DC's model, a 30 % cut after curfew alone takes Rock Creek Park from 225 to 301 stars after 01:00, more than the whole streetlight programme. A 50 % cut with the streetlight programme reaches 454.
3. **Full shielding at every replacement, and model-ranked retrofits now (1.1, 4.3).**
   - Permanent, and nearly free when specified at replacement.
   - Shielding everything roughly halves skyglow (Flagstaff).
   - In DC, fix the post-top globes first: 27 % of the streetlights' power, and 13 % of their remaining sky index once adaptive control is running.
4. **A measurement network on the ground and from orbit (4.2, 4.1).**
   - Six sky meters cost a few thousand dollars, and satellite data is free.
   - It is the only way to replace borrowed priors with DC's own numbers, prove each step worked and point enforcement at the sites that matter.
5. **Warm and amber spectrum at replacement, and presence-adaptive control where darkness matters most (1.2, 2.2).**
   - Start at park, river and habitat edges, where mean streetlight output can fall from 52 to 32 %.
   - Amber light carries about a sixth of 4000 K's dark-adapted skyglow per lumen, and far less melanopic and insect-attracting light.

**Why this order.** Items 1 and 2 are software and integration on hardware that already exists, so they are fast and pay for themselves. Item 3 rides the replacement cycle, so it must be in every specification now even though its effect accrues over years. Item 4 makes every other item verifiable. Item 5 adds the ecological protection that energy savings alone would not justify.

**What not to do first.**
- Do not buy adaptive controllers city-wide for energy savings: on DC's numbers they do not pay back on energy alone.
- Do not use satellites alone to judge a white-LED conversion; they miss the blue light.
- Do not deploy photoluminescent road markings at scale yet.

## 6. Sources

The [evidence review](EVIDENCE.md) carries the sources behind Nocturne's design. Those added here:

- Falchi, F., et al. (2016). The new world atlas of artificial night sky brightness. *Science Advances* 2:e1600377. Natural sky taken as 174 µcd/m² (22.0 mag/arcsec²); the Milky Way is lost above an artificial brightness of 688 µcd/m² (Table 1).
- IDA & IES (2011). *Joint IDA–IES Model Lighting Ordinance (MLO) with User's Guide*, 15 June 2011. Lighting zones LZ0–LZ4, Table B (hardscape lumen allowances), Table C (BUG limits), and the curfew reduction of at least 30 % (§III.C.2).
- Kuechly, H. U., et al. (2012). Aerial survey and spatial analysis of sources of light pollution in Berlin, Germany. *Remote Sensing of Environment* 126:39–50.
- Luginbuhl, C. B., Lockwood, G. W., Davis, D. R., Pick, K., and Selders, J. (2009). From the ground up I: light pollution sources in Flagstaff, Arizona. *PASP* 121:185–203, doi:10.1086/597625.
- NHTSA (2022). FMVSS No. 108, adaptive driving beam headlamps, final rule. *Federal Register* 87:9916, 22 February 2022.
⟦S6-more⟧
