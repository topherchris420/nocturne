# Cutting light pollution with technology: a proposal

**Executable next step:** [the restoration workflow](RESTORATION.md) now turns a declared source inventory, owner participation, service requirements and darkness targets into a least-cost intervention portfolio, then provides randomized source-isolation trial tools. Its worked example is explicitly synthetic.

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

Each technology against the four priorities: **E** saves energy, **A** adapts to real-time need, **S** optimises the spectrum, **D** controls direction or shields. Monitoring (section 4) makes the others measurable.

| | Technology | Priorities | Readiness | Indicative cost | Headline impact |
|---|---|---|---|---|---|
| [1.1](#11-full-cutoff-precision-optics-and-retrofit-shields) | Full-cutoff optics and retrofit shields | D | Commercial; globe retrofits early commercial | $250–500 per installed LED cobra-head | Shielding all lighting roughly halves skyglow (Flagstaff) |
| [1.2](#12-spectrum-warm-white-amber-and-tunable) | Warm, amber and tunable spectra | S | Commercial; tunable early commercial | PC-amber about 70 lm/W against 125+ for white | PC-amber: 83 % less dark-adapted skyglow per lumen than 4000 K |
| [1.3](#13-controls-in-the-luminaire-dimmable-drivers-clocks-vacancy-sensors-and-constant-light-output) | Dimmable drivers, clocks, vacancy sensors, constant light output | E A | Commercial | Sensor: tens to hundreds of dollars (ESTIMATE) | Garage saving 52 % → 88 % with occupancy dimming |
| [1.4](#14-building-envelopes-interior-light-kept-inside) | Interior light kept inside | E A | Commercial; feed-driven schedules prototype | Schedules: none. Electrochromic: +$37/ft² | Halving lit windows: 6–11 times fewer bird collisions |
| [1.5](#15-materials-that-do-the-job-of-light) | Retroreflective, photoluminescent and surface materials | E | Sheeting commercial; glowing paint pilot | Unlit sign: about $5,000 a year saved per structure | 17 of 48 US states light no overhead signs |
| [2.1](#21-time-of-night-dimming-on-the-controllers-a-city-already-has) | Time-of-night dimming on existing controllers | E | Commercial | Integration; pays back in 3 years under $1.9 M (DC) | DC: −30 % energy, $641,000 a year |
| [2.2](#22-presence-adaptive-lighting) | Presence-adaptive lighting | E A | Commercial; VDL-7 prototype | About $570 per light with LED and node (Chicago) | DC park edges: mean level 52 % → 32 % |
| [2.3](#23-controllers-that-keep-the-schedule-when-the-network-fails) | Controllers that keep the schedule offline | E A | Prototype | Firmware and a holdover clock | 7-hour outage: 0.65 of today's light, not 0.95 |
| [2.4](#24-output-that-follows-weather-and-surface) | Output that follows weather and surface | E A | Allowed by CIE 115; closed loop pilot | Weather data: none per pole | Acts on nights when cloud and snow multiply skyglow up to 188 times |
| [2.5](#25-guidance-instead-of-illumination-where-lighting-is-not-warranted) | Guidance instead of illumination | E | Commercial | Low (ESTIMATE) | No fixed light at all on those roads |
| [3.1](#31-sports-lighting-precision-optics-and-controls-tied-to-bookings) | Sports: precision optics, booking-linked control | E A D | Commercial | Two LED soccer fields: about $300,000 in materials | About 60 % less energy than metal halide |
| [3.2](#32-car-parks-and-area-lighting-lumen-budgets-and-occupancy-control) | Car parks: lumen budgets, occupancy control | E A D | Commercial; required by energy codes | Integrated sensors (ESTIMATE: tens of dollars) | LED 58 % saving, 74 % projected with bi-level control |
| [3.3](#33-signs-and-media-facades-brightness-that-follows-the-night) | Signs that follow ambient light, with curfew | E A | Commercial | Built into current digital signs | ≤ 0.3 fc above ambient; 300 cd/m² night cap (UK code) |
| [3.4](#34-facades-and-monuments-light-kept-on-the-surface) | Facades: framing optics, curfew, migration nights | E A D | Commercial | Framing projectors cost more than floods | Vienna: facades off at midnight darkened the zenith a further 0.09 mag |
| [3.5](#35-industrial-sites-ports-and-logistics-zoned-light-and-security-without-floodlight) | Zoned industrial light; thermal security | E A D | Commercial | Thermal cameras cost more (ESTIMATE) | Unmeasured: worth a pilot |
| [3.6](#36-greenhouses-blackout-screens) | Greenhouse blackout screens | D | Commercial; mandatory in the Netherlands and Leamington | No public price | 98–99 % of the light kept in |
| [4.1](#41-satellites-that-find-where-light-is-growing) | Satellites | — | Operational | Free data | France mapped switch-offs in 22,773 communes |
| [4.2](#42-ground-sensor-networks-and-the-curfew-step-method) | Ground sky meters, curfew-step method | — | Commercial; method prototype | About $2,000 for six stations | Shows a 0.05 mag change within a season |
| [4.3](#43-a-skyglow-digital-twin-to-aim-the-money) | Skyglow digital twin | — | Prototype | Software and staff | Ranks retrofits by sky regained |
| [4.4](#44-a-machine-readable-curfew-and-migration-signal) | Signed curfew and migration signal | E A | Prototype | Almost none for owners with automation | DC: a 30 % curfew on other lighting beats the whole streetlight programme |
| [4.5](#45-obstruction-lighting-that-waits-for-aircraft) | Obstruction lights that wait for aircraft | E A | Commercial; mandatory in Germany | €30,000 per wind park to €100,000 per turbine | Lights dark over 95 % of the night |

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
3. **Near-horizontal light travels furthest.**
   - A few kilometres out from a town, light emitted between the horizontal and 10° above it matters as much as light at all other angles together (Cinzano and Diaz Castro 2000).
   - A near-horizontal ray produces 6–160 times the sky glow of the same flux reflected off ground of 15 % reflectance. Fixtures that send just 3 % of their light upward produce 80–290 % more sky glow than fully shielded ones (Luginbuhl, Walker and Wainscoat 2009).
   - Direct uplight is 36 % of the zenith radiance downtown, but 86 % at 30 km (Aubé 2015).
   - Lit windows, unshielded wall packs and sideways floodlights emit exactly there.

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
- **New full-cutoff luminaires:** commercial (TRL 9), with a certification scheme. DarkSky Approved luminaires (guidelines v3, 2025) must keep uplight to 5 lm, or above 1,000 lm to 0.5 % of output and at most 50 lm. Their colour temperature may not exceed 3000 K, and above 500 lm they must dim to 10 %.
- **Reflector and baffle retrofits for globes:** early commercial (TRL 8), specific to each luminaire model. Full-cutoff replacement acorns are catalogue items.

**Cost and barriers.**
- **New luminaires:** a full-cutoff LED cobra-head cost roughly $250–500 installed in US city conversions of 2013–2021. Los Angeles paid $432 a fixture in 2009 and $245 in 2012, for hardware alone. Howard County, Maryland paid about $315 plus about $175 to install in 2021.
- **Globe retrofits:** no public unit price turned up. Truman State University fitted opaque tops to its globes because replacing them was "prohibitively expensive".

The barriers are a historic-district taste for glowing globes, a replacement cycle of one to two decades, and aiming that drifts in the field.

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
- Narrow-band amber: commercial, mostly in wildlife lighting. Florida's sea-turtle certification accepts only light above 560 nm with nothing below, mounted low and fully shielded. That rules out PC-amber, whose blue pump leaks through (FWC).
- Tunable white-to-amber roadway luminaires: early commercial.

**Cost and barriers.** Amber costs efficacy.
- **Qualification thresholds:** the DesignLights Consortium's 2025 thresholds, set at the median of listed products, are 70 lm/W for PC-amber and 30 lm/W for direct (narrow-band) amber luminaires. White outdoor luminaires must reach 125 lm/W, less 8 % at 2700 K and below and 10 % at 2200 K and below (DLC SSL V6.0).
- **Heat:** direct amber LEDs also fade when hot, from 100 lm/W at 25 °C to 38 at 85 °C, against 118 and 110 for PC-amber (Lumileds, DOE workshop 2020).
- **Nocturne's assumption:** the business case ASSUMES PC-amber at 0.70 of 3000 K's efficacy (`EFFICACY_REL` in `vdl7/spectral.py`). DLC's figures suggest nearer 0.5, so Phase 2's energy for the park-edge lights is optimistic. Those lights are under 1 % of the fleet's power, so the total barely moves.

The other barriers are colour rendering, public acceptance of amber, and procurement specifications that still ask for 3000–4000 K.

**Impact.**
- **DC streetlights:** at replacement, the Section 4 spectrum (2700 K arterials; 2200 K collectors, local streets and alleys; PC-amber at park edges) cuts the streetlights' annual sky index a further 6 % (0.581 → 0.545) for 5 % more energy (10.9 → 11.5 GWh, `nocturne business-case`).
- **Measured, the other way:** when Chelan County, Washington, replaced 3,693 sodium lights with full-cutoff LEDs, 80 % of them 3000 K, the sky got brighter and the glow reached higher overhead, even though the radiance satellites saw fell (Hung et al. 2021). Madrid's sky darkened 14 % in 2011–15, then brightened 32 % in 2015–19; the largest changes came as many streetlights moved from sodium to LED (Robles et al. 2021). The National Park Service's summary of the Chelan study: replacement LEDs must be below 3000 K, or dimmed more than 50 % relative to the sodium lights, to reduce skyglow.
- **Bats:** light-shy *Myotis* and *Plecotus* bats avoided white and green light, but were as common under red light as in darkness (Spoelstra et al. 2017).
- **Insects:** the spectral evidence is mixed.
  - Amber-filtered warm-white LEDs drew the fewest insects of the lamps compared in a Peruvian forest trial (Deichmann et al. 2021). A spectrally tuned 2700 K LED drew 20–21 % fewer than a commercial 2700 K LED (Longcore et al. 2015).
  - On the other hand, white LEDs caught 48 % more insects than sodium lamps, with no gain from changing colour temperature (Pawson and Bader 2014). In another trial, 2700 K and 6500 K made no difference to insects or bats (Bolliger et al. 2020).
  - The stakes are not in doubt: lit hedgerows held 47 % fewer moth caterpillars than unlit ones, and 52 % fewer under LED (Boyes et al. 2021).
  - Spectrum helps most when it removes blue light entirely. Dimming and switching off are the dependable measures.

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

**Cost and barriers.** Dimmable drivers and controller sockets are standard on current outdoor LED luminaires. A sensor adds tens to low hundreds of dollars per luminaire (ESTIMATE; no reliable public price turned up). Specify driver accuracy and verify savings with metering: in the PNNL study below, inaccurate 0–10 V dimming curves erased most of the CLO saving, and a third of what a part-night dimming schedule was designed to save (18 % designed, 12–13 % delivered). The barrier is that cheap residential and small-commercial fixtures still ship as dusk-to-dawn units with no dimming or sensing.

**Impact.**
- **CLO, on paper:** VDL-7's profile (86 % drive when new, rising to 100 % at 100,000 h) uses about 7 % less energy over the luminaire's life, and up to 14 % less light in its first years (`vdl7/profiles.py`). A Pacific Northwest National Laboratory study expected 5–10 %, for lumen depreciation of 10–20 %.
- **CLO, with real drivers:** the same study measured between −2 % and +3 %. The cause was inaccurate 0–10 V dimming curves: 9 of 19 drivers failed ANSI C137.1-2022 (Waghale et al. 2023).
- **Occupancy sensing:** it took a federal parking garage's saving from 52 % (LED alone) to 88 % (3.2).
- **Codes:** energy codes already require this for new commercial work: a cut of at least 50 % after hours or on vacancy (ASHRAE/IES 90.1-2016 and later), and 50–90 % on vacancy in California (Title 24). See 3.2.

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

**Cost and barriers.**
- **Schedules:** a change in an existing building automation system needs no hardware.
- **Electrochromic glass:** in a 2018 federal evaluation, insulated units cost about $61 per square foot installed, against $24 for low-e glazing, a premium of about $37 (about $400/m²). Energy savings repaid that premium in about 13 years for new construction and 29 years for retrofits (GSA 2018).

The barriers are night cleaning crews, late workers, and tenants' control of their own floors.

**Impact.**
- **Collisions:** at a Chicago convention centre where 11,567 birds died in collisions between 2000 and 2020, halving the lit window area is estimated to cut collisions 11-fold in spring and 6-fold in autumn (Van Doren et al. 2021).
- **Attraction:** when an intense installation goes dark, trapped birds disperse within minutes (Van Doren et al. 2017).
- **Transmission:** electrochromic glass tints from about 60 % visible transmittance to 1 %, so lights left on behind tinted glass leak about a sixtieth as much (SageGlass and View product data).

**Trade-offs and failure modes.**
- Occupants override blinds.
- Electrochromic glass takes minutes to tint, and reduces transmitted light rather than eliminating it: about 1 % still gets through at full tint.
- A schedule that fails must fail to "off after hours", not "on".

### 1.5 Materials that do the job of light

**What it is.**
- **Retroreflective sign sheeting:** microprismatic sheeting (the high-performance types of ASTM D4956, such as Type XI) returns headlight to the driver, so overhead guide signs need no luminaires of their own.
- **Photoluminescent markings:** strontium-aluminate paint that charges by day and glows at night.
- **Surfaces chosen for the lighting method:** dark or bright paving and facades, matched to how the space is lit.

**How it cuts light pollution.** Sheeting removes luminaires altogether, and overhead sign lights often sit below the sign aimed upward, so whatever misses the face goes into the sky. Photoluminescent paint replaces low-level wayfinding light. Surface choice sets how much of the downward light is reflected up: zenith radiance rises in proportion to ground reflectance (Aubé 2015). Paving ranges from about 5–10 % reflective for new asphalt to 35–40 % for new concrete (broadband solar reflectance, US EPA 2008).
- Where a road is designed to a *luminance* target, a brighter surface lets the luminaires deliver less light for the same visibility.
- Where a space is designed to an *illuminance* target, a brighter surface simply reflects more into the sky.
- The same conflict applies to high-albedo "cool" pavements and roofs installed against urban heat.

**Readiness.**
- Retroreflective sheeting: commercial.
- Photoluminescent road markings: pilot, with setbacks. The Netherlands' 2014 "Glowing Lines" on the N329 were faded out within weeks after rain disrupted their glow. Malaysia dropped a 245 m pilot in 2024, at about 19 times the cost of ordinary marking paint (RM749 against RM40 per m²).
- Surface selection: a design choice, available now.

**Cost and barriers.**
- **The rule:** the MUTCD (11th edition, 2023, §2E.10) says overhead signs should be lit unless an engineering study shows retroreflection alone performs effectively. Removal therefore needs that study.
- **Practice:** in a 2014 survey of 48 state transportation departments, 17 lit no overhead signs at all and 14 were removing lighting from existing structures. Illinois put the saving at about $5,000 a year per sign structure, and Washington at about $100,000 a year in electricity (Caltrans 2014).
- **DC:** its inventory lists 131 overhead-guide-sign luminaires, kept static today (`data/dc/fleet.json`). With high-performance sheeting and that study, they are candidates for removal.

**Impact.** Twenty of the surveyed states reported no adverse effects from unlit overhead signs (Caltrans 2014). Removing sign lighting takes all of it out of the sky, and it is often aimed upward.

**Trade-offs and failure modes.**
- Retroreflection serves only someone beside a light source, such as a driver, not a pedestrian.
- Photoluminescent glow is faint and fades through the night. It also suffers in damp: strontium aluminate hydrolyses, and even epoxy-coated films lost 57 % of their photoluminescence in a laboratory high-temperature, high-humidity test (Wang et al. 2020).

## 2. Street and municipal lighting

**First, the LED conversion itself.** It is the platform for everything below, and it saves energy on its own:
- Los Angeles used about 63 % less electricity once 141,089 lights were converted (2013);
- Phoenix about 53 % across roughly 100,000 lights (2020);
- Chicago more than halved its streetlight energy bill across more than 280,000 lights (2022).

Done carelessly, though, the conversion can brighten the sky (1.2). Every conversion should be fully shielded (1.1), warm (1.2), and dimmable and networked from day one (1.3), because the controllers are what make 2.1–2.3 possible.

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

**Measured elsewhere.** When Vienna cut part of its street lighting at 23:00, main roads excepted, the zenith darkened by 0.18 mag/arcsec² on average, about 15 % less light (Puschnig et al. 2014).

**Trade-offs and failure modes.**
- If a city already dims, its saving is smaller.
- People may feel less safe. The evidence is reassuring: across 62 local authorities in England and Wales, switch-off, part-night lighting and dimming showed little evidence of harm to night-time collisions or crime (Steinbach et al. 2015). Nocturne's rollout is still randomised, with a brake that pauses it if night-time crashes rise (`nocturne brake`).
- Real drivers deliver less dimming than designed. In a PNNL test of 0–10 V drivers, a schedule designed to save 18 % saved 12–13 % (Waghale et al. 2023). Count the saving from the nodes' own metering, not from the schedule.
- A controller that loses its network must not revert to full output (see 2.3).

### 2.2 Presence-adaptive lighting

**What it is.** A radar or passive-infrared sensor at each pole detects pedestrians, cyclists and vehicles.
- The node raises its own light, and over a local mesh the next three poles ahead (a "light carpet"), within two seconds, then fades back.
- Arterials follow live loop-detector volumes. CIE 115:2010 provides for this: its adaptive lighting classes change with time-dependent conditions such as traffic volume and weather.
- Firmware floors hold every road class at or above its IES RP-8 level, whatever the sensors or a signed message say.

The VDL-7 controller in `vdl7/controller.py` models all of this.

**How it cuts light pollution.** Empty streets can go darker than any fixed schedule would dare, above all local streets, alleys and park edges.

**Readiness.** Sensors and adaptive controllers are commercial, with field results behind them:
- on a Helsinki cycle and foot route, presence tracking by passive-infrared sensors saved 60–77 % against the existing control (Juntunen et al. 2018);
- in Davis, California, presence-adaptive networked LEDs used 27–42 % less energy than the same LEDs at a fixed level (UC Davis California Lighting Technology Center, preliminary).

The VDL-7 controller in this repository is a reference model (prototype).

**Cost and barriers.**
- **Hardware:** no reliable public price for a controller node alone turned up. Chicago's conversion came to about $570 per light, including the LED luminaire and its wireless node ($160 million for more than 280,000 lights).
- **Software:** central-system software and support ran about C$5 per light per year in Kitchener, Ontario (2018 staff report).
- **Energy alone does not pay for it.** The US Department of Energy judges that connected lighting's cost is "unlikely to be justified by energy savings alone", and DC's numbers agree. Once Phase 0 is running, a node would have to cost less than about $11 per pole to repay itself in ten years, or about $14 on local streets (`nocturne business-case`).

Its case is darkness where it matters most and light where people are. Deploy it first at park and river edges and on residential streets that ask for it.

**Impact in DC, beyond Phase 0.**
- Energy falls from 0.700 to 0.663 of today.
- Mean level falls on local streets from 58 to 52 %, in alleys from 55 to 42 % and on park edges from 52 to 32 %.
- After 01:00, the streetlights' contribution to the sky at the six places falls 48–56 %, against 44–46 % for Phase 0.

**Trade-offs and failure modes.**
- Missed detections (dark clothing, a blocked sensor, speed at the edge of range) must fail toward light, which is why the base level never drops below the class floor.
- False triggers from wind, foliage or animals erode the saving; the Helsinki trial saw them (Juntunen et al. 2018).
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

**How it cuts light pollution.** Fixed output does the most harm exactly when the scene needs least light:
- overcast skies multiplied the sky's luminance about tenfold inside Berlin, and 2.8-fold 32 km away (Kyba et al. 2011);
- at a suburban site near Berlin, fresh snow alone amplified the zenith luminance 33-fold, and snow with clouds 188-fold, against a clear, snow-free night (Jechow and Hölker 2019).

**Readiness.** CIE 115:2010 lets a road's lighting class change with weather and traffic, although the evidence behind its class-selection weightings is thin, at least for pedestrian routes (Fotios 2020). Closed-loop luminance control is at pilot stage.

**Cost and barriers.** Weather data from existing road-weather stations or forecasts costs nothing per pole. Luminance cameras need calibration, and the barrier is validating that the loop keeps visibility.

**Impact.** Not yet modelled in Nocturne. Skyglow scales with the light emitted, so a 30 % cut on an overcast or snowy night removes 30 % of a glow that can be ten or more times brighter than on a clear night. Those are the nights it reaches furthest into habitats.

**Trade-offs and failure modes.** Lenses foul and calibration drifts, so the loop must fall back to the base programme, never below the class floor.

### 2.5 Guidance instead of illumination where lighting is not warranted

**What it is.** On park drives, rural roads and river paths that do not need continuous light, delineation does the job:
- raised retroreflective pavement markers, solar LED road studs and reflective edge posts;
- on the vehicle, adaptive driving beam (ADB) headlamps, which keep the high beam on except where it would dazzle someone. They have been legal on new US vehicles since NHTSA amended FMVSS No. 108 in February 2022.

**How it cuts light pollution.** There is no fixed light on those segments at all.

**Readiness.** Commercial.

**Cost and barriers.** Markers and studs cost little next to a lighting installation, and have no energy bill (ESTIMATE; no reliable public comparison turned up). The barrier is a segment-by-segment risk assessment against crash data.

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

**Cost and barriers.**
- A manufacturer's budget estimate for LED lighting on two soccer fields in Bryant, Arkansas, came to $294,000–325,000 for materials, against $208,000–230,000 for metal halide, with installation extra (Musco).
- A stadium retrofit from metal halide to LED in Great Bend, Kansas, cost $158,400 installed.

The barrier is that up-front premium, which energy and maintenance savings repay only in part.

**Impact.**
- **Manufacturer's claims:** at least 50 % less spill light and glare, and 50–85 % lower energy and maintenance costs than typical 1,500 W metal-halide lighting (Musco).
- **An independent review** for Wellesley, Massachusetts accepted about 60 % less energy than metal halide. It warned that a 6.75-million-lumen installation would still create glare and light trespass and add to sky glow (Parks 2021).

Better optics do not make a stadium dark; hours do. Booking-linked control matters as much as the luminaire.

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

**Readiness.** Commercial, and required for new work by energy codes:
- **ASHRAE/IES 90.1:**
  - The 2010 edition (§9.4.1.7) switches facade and landscape lighting off from midnight, or closing, until 6 a.m. or opening. Other exterior lighting, signs included, must fall at least 30 % after hours, or after 15 minutes without activity.
  - From the 2016 edition (§9.4.1.4) that cut is at least 50 %. Car-park luminaires above 78 W mounted 24 ft or lower must also drop at least 50 % after 15 minutes without activity.
- **California's Title 24** (2019, §130.2(c)) requires motion-sensing controls that cut power by 50–90 % within 15 minutes of an area emptying, on outdoor luminaires mounted 24 ft or lower.

**Cost and barriers.** Occupancy sensors integrated in LED area luminaires add little to their price. No reliable public unit price was found (ESTIMATE: tens of dollars per luminaire). The barriers are owners' fear that an empty, dim car park invites crime, camera systems that need light (see 3.5), and the large stock of existing lots that codes reach only at renovation.

**Impact.**
- **LED alone:** in a US Department of Energy demonstration at a store car park in Manchester, New Hampshire, LED area luminaires saved 58 % against metal halide.
- **Occupancy sensing:** that rose to a projected 74 % with bi-level control, assuming 7 of 12 night hours at the low level (PNNL 2010). A bi-level lot at Cal Poly San Luis Obispo ran at its low level 68 % of the time.
- **In a garage:** a parking garage at the Department of Labor saved 52 % with LED, and 88 % once occupancy sensors dimmed it to 10 % after 2.5 minutes without activity (Kinzey and Myer 2013).
- **Fuel-station canopies:** they often run day and night, and occupancy control is their largest saving (PNNL 2011).

**Trade-offs and failure modes.**
- Poles that sway in the wind trigger their own sensors, which can significantly erode the savings (PNNL 2011).
- Sensor coverage has gaps at the edges of large lots.
- Re-brightening must be fast enough that a driver never enters a dark lot.

Software can check a permit application's photometric files for both the lumen budget and the BUG ratings automatically, as `nocturne bug` does for one luminaire.

### 3.3 Signs and media facades: brightness that follows the night

**What it is.**
- Digital billboards and electronic signs with photometers that hold brightness a fixed margin above ambient light, under a night-time luminance cap.
  - **Ambient margin:** the US outdoor-advertising industry's guideline is at most 0.3 foot-candles above ambient, measured at a distance set by the sign's size, with a photocell, not a sunset table, doing the control (OAAA).
  - **Night cap:** the UK industry code allows at most 300 cd/m² for displays over 10 m², and 600 cd/m² for smaller ones, from sunset to sunrise in urban and suburban areas (Outsmart 2021, following the Institution of Lighting Professionals' PLG05).
- Switch-off or deep dimming after the business closes, on the city's curfew feed.
- Static signs lit from above and aimed down, or internally lit with dark backgrounds.

**How it cuts light pollution.** At night ambient light is low, so a sign that tracks it runs at a small fraction of its daytime luminance, and a curfew removes it after close.

**Readiness.** Commercial: ambient dimming is built into current digital billboards.

**Cost and barriers.** Little hardware beyond what current signs carry. The barrier is advertising revenue tied to hours lit.

**Impact.** No measurement of signs' share of a big city's skyglow turned up. In Flagstaff, which has regulated outdoor lighting since 1989, signs were well under 1 % of outdoor lumens: about 0.6 million (±50 %) of 173 million (Luginbuhl et al. 2009). Where screens are unregulated their share is unmeasured, which is itself a reason for the monitoring in section 4.

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

**Impact.**
- **Vienna:** switching facade lighting off at midnight darkened the zenith by a further 0.09 mag/arcsec², on top of the 0.18 mag from the city's partial street-lighting cut at 23:00 (Puschnig et al. 2014).
- **Balaguer, Spain:** a scheduled switch-off showed ornamental lighting supplying more than 20 % of the zenith skyglow on a clear night (Jechow et al. 2018).
- **Birds:** switching off an intense installation released trapped migrating birds within minutes (Van Doren et al. 2017).

**Trade-offs and failure modes.** Top-down lighting is not always possible on historic buildings, and a precisely framed beam drifts if the projector is knocked.

### 3.5 Industrial sites, ports and logistics: zoned light, and security without floodlight

**What it is.**
- Yards zoned and lit only where vehicles or staff are, triggered by occupancy sensors, gate events or vehicle telematics.
- Flat-glass floodlights mounted level, with zero tilt.
- Thermal and near-infrared cameras with video analytics for perimeter security, bringing visible light on only when an alarm needs it. Thermal cameras detect people in complete darkness (manufacturers' specifications).

**How it cuts light pollution.** It replaces all-night security floodlighting, among the most upward-leaking lighting there is, with light on demand.

**Readiness.** Commercial.

**Cost and barriers.** Thermal cameras cost several times as much as visible-light ones (ESTIMATE). The barriers are insurers' and security contractors' habit of specifying light, and work zones that need light during operations.

**Impact.**
- No measured skyglow figure for industrial sites turned up. In Flagstaff, industrial lighting installed before the 1989 code sent about 13 % of its light straight up (Luginbuhl et al. 2009).
- Light can deter crime: temporary lights cut night-time outdoor index crimes by at least 36 % in a randomised trial in New York City public housing (Chalfin et al. 2022).
- The aim is therefore light on demand where people and threats are, not darkness everywhere. We found no study that measured crime when a site swapped standing floodlight for thermal detection with light on alarm; that is worth a pilot.

**Trade-offs and failure modes.**
- Thermal cameras cost more than visible-light ones.
- Near-infrared illuminators at 850 nm glow faintly red; 940 nm is invisible but shorter-ranged.
- Workers need light where they work, so zoning must follow operations, not just the clock.

### 3.6 Greenhouses: blackout screens

**What it is.** Light-tight screens (blackout or aluminised fabrics) drawn across greenhouse roofs and walls at night while supplementary grow lights are on, with sealed gaps and side walls.

**How it cuts light pollution.** It contains the light physically, where grow lights would otherwise light the clouds over whole farming districts.

**Readiness.** Commercial, and mandatory in places:
- **Netherlands:** under the Besluit activiteiten leefomgeving (art. 4.790, in force 2024), greenhouses lit at 15,000 lux or more must screen at least 98 % of their light through the roof from sunset to sunrise, and 95 % through the walls.
- **Leamington, Ontario:** By-law 41-22 (2022) requires curtains that block 99 % of light, with walls closed from 5 p.m. to 8 a.m.
- Blackout fabrics are rated at 99–99.9 % shading (manufacturer's data, Ludvig Svensson).

**Cost and barriers.** Screens are a capital cost, and no public per-area price turned up. The barrier is climate control: growers open screens to vent heat and humidity. Leamington, for one, requires ceiling curtains to be only 90 % closed in the evening and early morning.

**Impact.** During screened hours, 98–99 % of the light stays inside. An open gap or a part-open screen leaks in proportion.

**Trade-offs and failure modes.** Heat and humidity build up under closed screens, and a torn screen or open gap leaks light.

## 4. Regional and satellite monitoring and control

### 4.1 Satellites that find where light is growing

**What it is.** Night-time radiance from orbit, at two scales.
- **City-wide, every night:**
  - The VIIRS Day/Night Band on Suomi NPP, NOAA-20 and NOAA-21 sees 500–900 nm, in pixels of about 750 m, with overpasses near 01:30 local time.
  - NASA's Black Marble products build on it: daily, monthly and yearly radiance at 15 arc-seconds since 2012, corrected for moonlight, atmosphere, snow, vegetation and stray light.
- **Street-level and in colour:**
  - SDGSAT-1's Glimmer imager: 10 m panchromatic and 40 m colour, launched in November 2021, with an evening pass near 21:30.
  - Commercial night imagery: Jilin-1 offers colour at under 1 m.
  - More than a million night-time photographs taken from the International Space Station.

Change detection on these images flags new or brightened sources for inspection, tracks trends, and helps build the inventory of private lighting that no city database holds.

**How it cuts light pollution.** Indirectly: it shows where light is growing, aims inspections and retrofits, and checks that a programme happened.

**Readiness.**
- **VIIRS and Black Marble:** operational and free.
- **SDGSAT-1:** a research mission whose data have been open worldwide since 2022. By November 2024 it had acquired more than 400,000 scenes, for users in 104 countries.
- **Dedicated night-light missions:** at concept stage; ESA's Night Watch study ran in 2022–23.

**Cost and barriers.** VIIRS, Black Marble and SDGSAT-1 data are free, and commercial imagery is bought by the scene. The real cost is analysts' time. The barrier is that most lighting rules have no satellite-based enforcement path: we found no case of satellite data being used against an individual violator.

**Impact.**
- **Seeing a whole country at once:** France mapped street-lighting switch-offs in 22,773 communes from monthly VIIRS composites, and found that 73 % now switch off fully or partly (Cerema, OFB and DarkSkyLab 2026).
- **But also the limits:**
  - From orbit, the lit area of Earth grew 2.2 % a year from 2012 to 2016, and its radiance 1.8 % (Kyba et al. 2017).
  - On the ground, 51,351 citizen observations show the sky brightening 7–10 % a year from 2011 to 2022 (Kyba et al. 2023).
  - The difference is light that satellites do not see.

**Trade-offs and failure modes.**
- **Blind to blue:** the Day/Night Band is effectively blind below 500 nm, where white LEDs emit their blue (Kyba et al. 2017). A city converting to white LEDs can therefore look darker from orbit while its sky gets brighter, as Chelan County's did (1.2).
- **Wrong angle:** satellites see mostly light leaving steeply upward, whereas distant skyglow is driven by near-horizontal light.
- **Coarse view:** fixed overpass times, coarse pixels, and interference from cloud, moonlight and snow. VIIRS can tell which communes switch off, but not whether a single luminaire is shielded or warm.

### 4.2 Ground sensor networks and the curfew-step method

**What it is.**
- **Stations:** low-cost photometers (Unihedron SQM-LU-DL, the STARS4ALL TESS-W) logging zenith brightness every few minutes at fixed sites, plus all-sky cameras for the whole hemisphere and its colour.
- **Method:** `nocturne verify` keeps readings taken in full darkness with the Moon down and steady skies. It then measures, night by night, the step in brightness across the 23:00 curfew, before and after go-live.

**How it cuts light pollution.** It closes the loop:
- it replaces the borrowed Tucson share with DC's own (`nocturne sky --measured rock-creek=18.4`);
- it shows whether a programme worked;
- it flags backsliding.

**Readiness.** The instruments are commercial. The curfew-step method in `vdl7/observe.py` is a prototype, tested on a season of synthetic readings with clouds and moonlight.

**Cost and barriers.**
- **Instruments:** a logging SQM-LU-DL costs about $287, or $333 weatherproofed (Unihedron). A Wi-Fi TESS-W, which streams its readings in real time, costs €275 (Universidad Complutense de Madrid). Six DC stations come to about $2,000 of instruments, before mounting and upkeep.
- **Precision:** units agree to about ±0.1 mag/arcsec². The STARS4ALL network had more than 200 TESS-W photometers by 2021.

The barrier is upkeep: a dirty window, a dead battery or a moved mount silently corrupts a record.

**Impact.** Weather, season and aerosol cancel within a night. The curfew step therefore shows a 0.05 mag/arcsec² change in a single season, where a naive before-and-after comparison of the late-night sky is about ten times noisier ([playbook](PLAYBOOK.md)).

**Trade-offs and failure modes.**
- Sensors drift and age, so they need cross-calibration.
- A zenith-only photometer misses the horizon glow that matters to wildlife and to distant observatories.

### 4.3 A skyglow digital twin to aim the money

**What it is.** A radiative-transfer model of the city's light inventory and its atmosphere, calibrated against the ground network. It ranks every block's possible retrofits by the sky they would regain at protected places per dollar, and tests a policy before it is adopted. Nocturne's model is single scattering on DC's real grid; research models such as Illumina add multiple scattering, terrain and obstacles. In an Illumina study of the sky over Haleakalā, removing direct uplight roughly halved the sky radiance, and PC-amber LEDs gave about a third of today's scotopic sky brightness (Aubé et al. 2018).

**How it cuts light pollution.** The distance kernel falls steeply, so the same retrofit is worth far more near a park than across town. The twin spends the budget where it buys the most sky.

**Readiness.** Prototype (`vdl7/skyglow.py`); research models are mature but need expert users.

**Cost and barriers.** Software and staff time. The barrier is the inventory: cities rarely hold one for private lighting, which satellites (4.1) and permit files can fill.

**Impact.** In DC, `nocturne sky --retrofits 10` puts first a cell near Anacostia Park whose 5 kW of post-top globes, once fixed, remove 2.5 % of the streetlight sky there.

**Trade-offs and failure modes.** Absolute brightness depends on assumed aerosol and reflectance. Beyond about 30 km, single scattering without Earth curvature or terrain is optimistic. Calibrate against measurements and rank by *relative* gain.

### 4.4 A machine-readable curfew and migration signal

**What it is.** One public feed, signed by the city each evening, as JSON and as a calendar (`nocturne signal`). It carries:
- dusk and dawn, and the Moon;
- the moment each phase begins, resolved through local daylight-saving time;
- whether a heavy bird-migration night is forecast. BirdCast forecasts nightly migration across the contiguous US from a model trained on weather radar, and flags nights in the season's top 10 % as the ones when turning lights out matters most;
- for each kind of non-street lighting (facades, signs, empty office floors, car parks, sports fields), the recommended output in each phase.

Building automation, sign controllers, sports-field controllers and smart-home hubs subscribe and act on it, and the signature lets them trust it.

**How it cuts light pollution.** It synchronises every owner's existing controls with the curfew and with migration nights, at almost no marginal cost. Where curfew hours become law, it becomes the compliance clock. France's 2018 order on light nuisance sets switch-off times for non-residential lighting, caps new luminaires' upward light below 1 %, and caps colour temperature at 3000 K, or 2400 K in protected areas (arrêté of 27 December 2018, as summarised by ANPCEN).

**Readiness.** Prototype (`vdl7/nightsignal.py`). The automation it drives is commercial, and BirdCast forecasts are operational.

**Cost and barriers.** Publishing costs almost nothing. For a subscriber it is one schedule integration in the building automation or sign controller that is already there. The barrier is participation, which is voluntary until the law says otherwise.

**Impact.** This is the lever the DC table at the top turns. With the rest of the city's lighting halved after 23:00, Rock Creek Park after 01:00 goes from 246 stars (streetlight programme alone) to 454. Even the ordinance-minimum 30 % cut beats the whole streetlight programme.

**Trade-offs and failure modes.**
- If the feed is down, a subscriber must keep its last schedule rather than revert to all-on.
- An unsigned feed could be spoofed to switch a district's lights.
- Compliance is invisible without measurement (4.1, 4.2).

### 4.5 Obstruction lighting that waits for aircraft

**What it is.** Aircraft detection lighting systems (ADLS) on wind turbines and tall towers. A dedicated radar, or a transponder receiver, detects approaching aircraft, and the obstruction lights stay dark until one is near. On communication towers, flashing-only lighting replaces steady-burning red lights.

**How it cuts light pollution.** It removes most of the red blinking that marks the night horizon around wind farms, and the steady lights that draw migrating birds into towers.

**Readiness.** Commercial.
- **United States:** the FAA added ADLS standards to its obstruction-marking circular in December 2015 (AC 70/7460-1L, chapter 14).
- **Germany:** demand-controlled night marking has been required on wind turbines since 1 January 2025, with transponder-based systems allowed (EEG 2023 §9(8)).

**Cost and barriers.** Germany's government estimated about €100,000 per turbine for radar-based systems, or about €30,000 per wind park with transponder-based detection (Bundestag Drucksache 19/6714, 2018). No authoritative US cost per wind farm turned up.

**Impact.**
- **Wind farms:** the lights stay dark nearly all night. One vendor claims the lights are off 98 % of the time (Vestas). Modelling for the Vineyard Wind offshore farm put them on 3 h 49 min a year, under 0.1 % of conventional on-time. A US utility reports a cut of more than 95 % (MidAmerican Energy).
- **Communication towers:** towers with flashing lights only killed 3.7 birds each per season, against 13.0 where steady-burning lights were added, a possible cut of 50–71 % (Gehring et al. 2009). Since the FAA's 2015 circular, new towers over 350 ft may not use steady-burning red L-810 lights.

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
   - Six sky meters cost about $2,000 in instruments, and satellite data is free.
   - It is the only way to replace borrowed priors with DC's own numbers, prove each step worked and point enforcement at the sites that matter.
5. **Warm and amber spectrum at replacement, and presence-adaptive control where darkness matters most (1.2, 2.2).**
   - Start at park, river and habitat edges, where mean streetlight output can fall from 52 to 32 %.
   - Amber light carries about a sixth of 4000 K's dark-adapted skyglow per lumen, and a tenth of its melanopic content.

**Why this order.** Items 1 and 2 are software and integration on hardware that already exists, so they are fast and pay for themselves. Item 3 rides the replacement cycle, so it must be in every specification now even though its effect accrues over years. Item 4 makes every other item verifiable. Item 5 adds the ecological protection that energy savings alone would not justify.

**Outside the city.** Aircraft-detection lighting on wind farms and towers (4.5) is the quickest regional win: it is commercial, mandatory in Germany, and keeps obstruction lights dark more than 95 % of the night.

**What not to do first.**
- Do not buy adaptive controllers city-wide for energy savings: on DC's numbers they do not pay back on energy alone.
- Do not use satellites alone to judge a white-LED conversion; they miss the blue light.
- Do not deploy photoluminescent road markings at scale yet.

## 6. Sources

Every source this page cites. The [evidence review](EVIDENCE.md) covers the research behind Nocturne's design in more depth. Manufacturers' figures are claims, not independent measurements.

**Research papers**

- Aubé, M. (2015). Physical behaviour of anthropogenic light propagation into the nocturnal environment. *Phil. Trans. R. Soc. B* 370:20140117.
- Aubé, M., et al. (2018). *MNRAS* 478:1776–1783 (Illumina model of the sky over Haleakalā).
- Barentine, J. C., et al. (2020). *J. Quant. Spectrosc. Radiat. Transf.*, doi:10.1016/j.jqsrt.2020.107120.
- Bolliger, J., et al. (2020). *Journal of Insect Conservation* 24:625–635.
- Boyes, D. H., et al. (2021). Street lighting has detrimental impacts on local insect populations. *Science Advances* 7:eabi8322.
- Chalfin, A., Hansen, B., Lerner, J., and Parker, L. (2022). *J. Quant. Criminol.* 38:127–157.
- Cinzano, P., and Diaz Castro, F. J. (2000). The artificial sky luminance and the emission angles of the upward light flux. *Mem. Soc. Astron. Ital.* 71:251, arXiv:astro-ph/9811297.
- Deichmann, J. L., et al. (2021). *Insect Conservation and Diversity* 14:247–259, doi:10.1111/icad.12479.
- Falchi, F., et al. (2016). The new world atlas of artificial night sky brightness. *Science Advances* 2:e1600377. Natural sky taken as 174 µcd/m² (22.0 mag/arcsec²); the Milky Way is lost above an artificial brightness of 688 µcd/m² (Table 1).
- Fotios, S. (2020). A review of design recommendations for P-class road lighting in European and CIE documents, part 1: parameters for choosing a lighting class. *Lighting Res. Technol.* 52:607–625.
- Gehring, J., et al. (2009). *Ecological Applications* 19:505–514.
- Hung, L.-W., et al. (2021). *J. Environ. Management* 292:112776, arXiv:2107.02026.
- Jechow, A., et al. (2018). *J. Quant. Spectrosc. Radiat. Transf.* 209:212–223, arXiv:1808.10224.
- Jechow, A., and Hölker, F. (2019). Snowglow: the amplification of skyglow by snow and clouds can exceed full moon illuminance in suburban areas. *J. Imaging* 5:69.
- Juntunen, E., et al. (2018). Smart and dynamic route lighting control based on movement tracking. *Building and Environment* 142:472–483.
- Kuechly, H. U., et al. (2012). Aerial survey and spatial analysis of sources of light pollution in Berlin, Germany. *Remote Sensing of Environment* 126:39–50.
- Kyba, C. C. M., et al. (2011). Cloud coverage acts as an amplifier for ecological light pollution in urban ecosystems. *PLoS ONE* 6:e17307.
- Kyba, C. C. M., et al. (2017). Artificially lit surface of Earth at night increasing in radiance and extent. *Science Advances* 3:e1701528.
- Kyba, C. C. M., et al. (2021). *Lighting Res. Technol.* 53:189–211, doi:10.1177/1477153520958463.
- Kyba, C. C. M., et al. (2023). *Science* 379:265–268, doi:10.1126/science.abq7781.
- Longcore, T., et al. (2015). Tuning the white light spectrum of light emitting diodes to reduce attraction of nocturnal arthropods. *Phil. Trans. R. Soc. B* 370:20140125.
- Luginbuhl, C. B., Lockwood, G. W., Davis, D. R., Pick, K., and Selders, J. (2009). From the ground up I: light pollution sources in Flagstaff, Arizona. *PASP* 121:185–203, doi:10.1086/597625.
- Luginbuhl, C. B., Walker, C. E., and Wainscoat, R. J. (2009). Lighting and astronomy. *Physics Today* 62(12):32.
- Pawson, S. M., and Bader, M. K.-F. (2014). LED lighting increases the ecological impact of light pollution irrespective of color temperature. *Ecological Applications* 24:1561–1568.
- Puschnig, J., Posch, T., and Uttenthaler, S. (2014). Night sky photometry and spectroscopy performed at the Vienna University Observatory. *J. Quant. Spectrosc. Radiat. Transf.*, arXiv:1304.7716.
- Robles, J., et al. (2021). *Remote Sensing* 13:1511 (Madrid).
- Spoelstra, K., et al. (2017). Response of bats to light with different spectra: light-shy and agile bat presence is affected by white and green, but not red light. *Proc. R. Soc. B* 284:20170075.
- Steinbach, R., et al. (2015). The effect of reduced street lighting on road casualties and crime in England and Wales. *J. Epidemiol. Community Health* 69:1118–1124.
- Van Doren, B. M., et al. (2017). *PNAS* 114:11175–11180.
- Van Doren, B. M., et al. (2021). Drivers of fatal bird collisions in an urban center. *PNAS* 118:e2101666118.
- Wang et al. (2020). Preparing and testing the reliability of long-afterglow SrAl₂O₄:Eu²⁺,Dy³⁺ phosphor flexible films for temperature sensing. *RSC Advances*, doi:10.1039/d0ra00628a.

**Government, laboratory and standards documents**

- ANPCEN: summary of France's *arrêté* of 27 December 2018 on light nuisance, https://www.anpcen.fr/index.php5?id_rub=&id_ss_rub=127&id_actudetail=232
- Bundestag Drucksache 19/6714 (2018), cost of demand-controlled night marking, https://dserver.bundestag.de/btd/19/067/1906714.pdf; and EEG 2023 §9(8), the 1 January 2025 duty.
- Caltrans / CTC & Associates (2014). Type XI sign sheeting: preliminary investigation and survey of state DOTs, https://dot.ca.gov/-/media/dot-media/programs/research-innovation-system-information/documents/preliminary-investigations/type-xi-sign-sheeting-pi-a11y.pdf
- Cerema, OFB and DarkSkyLab (2026). *Cartographie nationale des pratiques d'éclairage nocturne*, technical report, https://static.data.gouv.fr/resources/cartographie-nationale-des-pratiques-declairage-nocturne/20260812-085049/rapport-technique-cartographie-extinctions-2026.pdf
- CIE 115:2010, *Lighting of roads for motor and pedestrian traffic*; CIE 191:2010, *Recommended system for mesopic photometry based on visual performance*.
- DarkSky International (2025). DarkSky Approved Luminaires Program Guidelines, v3.0 and v3.1.
- DesignLights Consortium (2025). SSL Technical Requirements V6.0, released 3 November 2025.
- ESA Night Watch concept study (2022–23), https://www.gfz.de/sektion/fernerkundung-und-geoinformatik/projekte/abgeschlossene-projekte/night-watch
- FAA Advisory Circular 70/7460-1L (December 2015), *Obstruction Marking and Lighting*, chapter 14 (aircraft detection lighting systems) and its tower-lighting changes.
- FHWA (2023). *Manual on Uniform Traffic Control Devices*, 11th edition, §2E.10.
- Florida Fish and Wildlife Conservation Commission: wildlife lighting criteria, https://myfwc.com/conservation/you-conserve/lighting/criteria/
- GSA Green Proving Ground (2018). Electrochromic windows findings, https://origin-www.gsa.gov/system/files/12-Electrochromic%20Windows.pdf
- IDA & IES (2011). *Joint IDA–IES Model Lighting Ordinance (MLO) with User's Guide*, 15 June 2011. Lighting zones LZ0–LZ4, Table B (hardscape lumen allowances), Table C (BUG limits), and the curfew reduction of at least 30 % (§III.C.2).
- Kitchener, Ontario (2018). Staff report on the LED streetlight central management system, https://lf.kitchener.ca/WebLinkExt/0/doc/1610311/Page1.aspx
- Kinzey, B., and Myer, M. (2013). Demonstration of LED parking garage lighting at the US Department of Labor, PNNL-22388, https://www.osti.gov/biblio/1079130
- Leamington, Ontario (2022). By-law 41-22, greenhouse light abatement.
- NASA Black Marble User Guide v1.3 (2022), and Román, M. O., et al. (2018), *Remote Sensing of Environment* 210:113–143.
- Netherlands (2024). *Besluit activiteiten leefomgeving*, art. 4.790, greenhouse light screening.
- NHTSA (2022). FMVSS No. 108, adaptive driving beam headlamps, final rule. *Federal Register* 87:9916, 22 February 2022.
- OAAA. Recommended digital billboard brightness guidelines, https://oaaa.org/wp-content/uploads/2026/03/OAAA-Recommended-Digital-Brightness-Guidelines_AM20260311.pdf
- Outsmart (2021). *Large Format Digital Roadside Code*, following the ILP's PLG05.
- PNNL (2010). GATEWAY demonstration of LED parking-lot lighting, Manchester, New Hampshire, PNNL-19475, https://www.pnnl.gov/main/publications/external/technical_reports/PNNL-19475.pdf
- PNNL (2011). PNNL-20579, https://www.pnnl.gov/main/publications/external/technical_reports/PNNL-20579.pdf
- SDGSAT-1: Chinese Academy of Sciences (2022), open data programme, https://english.cas.cn/newsroom/news--archives/2022/news-updates/202209/t20220923_1125891.shtml; AIRCAS (2024), scenes and users.
- UC Davis California Lighting Technology Center: networked LED streetlights, Davis, https://cltc.ucdavis.edu/project/networked-led-streetlights
- US Department of Energy: connected lighting systems, https://www.energy.gov/eere/buildings/articles/connected-lighting-systems
- US EPA (2008). *Reducing Urban Heat Islands*, chapter 5, Cool Pavements (draft), https://www.epa.gov/sites/default/files/2017-05/documents/reducing_urban_heat_islands_ch_5.pdf
- Waghale et al. (2023). *The Energy and Operational Impacts of Using 0–10V Control for LED Streetlights*, PNNL, https://www.pnnl.gov/publications/energy-and-operational-impacts-using-0-10v-control-led-streetlights

**Programmes, products and press**

- City conversions: Los Angeles (US DOE SSL posting, 29 January 2013; CleanTechnica, 12 September 2013), Phoenix (KTAR, 15 January 2020), Chicago (EC&M, 23 February 2022), Howard County, Maryland (Maryland Energy Administration newsletter, July 2021).
- Sports lighting: Musco budget estimate for Midland Park soccer fields, Bryant, Arkansas (2020), https://www.bryantar.gov/grab/agendas/uploads/agenda_82/midland_park_soccer_led_and_hid_budget_estimate.pdf; Parks, B. (2021), review of athletic field lighting for Wellesley, Massachusetts, https://wellesleyma.gov/DocumentCenter/View/24601/Wellesley-Athletic-Field-Lighting-5-19-21; *Great Bend Tribune*, Memorial Stadium lighting.
- Photoluminescent markings: *Construction Management* on the N329 Glowing Lines (2014); *Motorist* (Malaysia), November 2024.
- Globe retrofits: Truman State University dark-sky project, https://darksky.truman.edu/?p=141
- Electrochromic glass: SageGlass and View product data.
- Amber LEDs: Lumileds presentation to the US DOE SSL R&D workshop, January 2020, https://www.energy.gov/sites/default/files/2020/02/f71/ssl-rd2020-epler-amber.pdf
- Greenhouse screens: Ludvig Svensson OBSCURA product data.
- Sky meters: Unihedron SQM prices and instruction sheet; Universidad Complutense de Madrid, TESS-W, https://guaix.fis.ucm.es/tess/
- Aircraft detection lighting: Vestas (2017); Vineyard Wind construction and operations plan, appendix III-N (BOEM); MidAmerican Energy (2026).
- BirdCast migration forecasts, https://birdcast.org/migration-tools/migration-forecast-maps/
- Jilin-1 night imagery: Guk, E., and Levin, N. (2020), *ISPRS J. Photogramm. Remote Sens.* 163:121–136. International Space Station photographs: Sánchez de Miguel, A., et al. (2021), arXiv:2108.07050.
