# What the research says, and how Nocturne uses it

This page collects the research the design leans on, what each source actually found, and where it sits in the code. Where a finding cuts against the project, it is reported anyway.

## 1. Dimming streets does not, on the evidence, cost safety. Light where people are does help.

**Steinbach et al. 2015**, *J Epidemiol Community Health* 69:1118–1124. Controlled interrupted time series across **62 local authorities in England and Wales**, using police data on night-time road collisions (2000–2013) and crime (2010–2013).
- They found "little evidence of harmful effects" on collisions or crime from any of four changes: switch-off, part-night lighting, dimming, or white/LED light.
- Dimming and white light were weakly associated with *less* aggregate crime: RR 0.84 (95 % CI 0.70–1.02) and 0.89 (0.77–1.03). Neither result is significant.
- Limits: the study could not separate out other safety programmes, such as CCTV or new road markings. Its cost-benefit analysis also could not count fear of crime or reduced mobility.

**Chalfin, Hansen, Lerner and Parker 2022**, *J Quant Criminol* 38:127–157. A **randomised** trial in New York City public housing developments (2016). Temporary streetlights reduced **night-time outdoor index crime by at least 36 %**.

**How the design reconciles the two:**
- Light falls when nobody is there and comes back within two seconds when someone is: radar presence, a 3-pole light carpet ahead of the walker, and live loop volumes on arterials.
- Firmware floors keep every class at or above its RP-8 class, whatever a signed bundle says.
- High-Injury Network segments never drop below 60 %.
- Emergencies go to 100 % inside a 400 m CAD geofence.
- Code: `vdl7/controller.py` (steps 4–9), `vdl7/profiles.py` (`FIRMWARE_MIN_FLOOR`, `FIRMWARE_MIN_HIN`).

**Rather than ask DC to take this on trust, the rollout tests it.**
- `vdl7/pilot.py` randomises DC's 12,106 lit street segments into a stepped wedge, stratified by ward and road class.
- At each wave, an exact rate-ratio test on night-time crashes acts as a brake.
- DC's open crash layer recorded **18,173 crashes in 2025**. Between 44 % and 56 % happened with the sun below −3°, depending on whether the layer's `FROMDATE` is read as UTC or local time. That gives on the order of 0.002 night crashes per lit segment-night.
- At that rate, detecting a 20 % change needs about 190,000–240,000 segment-nights per arm (`nocturne pilot --power 0.0018 1.2`). The wedge reaches that by its second look.

## 2. Streetlights are a minority of skyglow. That sets the ambition.

**Barentine et al. 2020**, *J Quant Spectrosc Radiat Transf*, doi:10.1016/j.jqsrt.2020.107120 (arXiv:2005.12357). In Tucson's 2019 experiment, the city dimmed and brightened its fully inventoried LED streetlights over several nights. Radiative-transfer modelling of the result attributes **about (14 ± 1) % of the emissions behind the city's skyglow** to municipal streetlights.

**Kyba et al. 2021**, *Lighting Res Technol* 53(3):189–211, doi:10.1177/1477153520958463. In the same experiment seen from orbit (VIIRS):
- City-operated streetlights were **13 % (95 % CI 10–16 %)** of Tucson's upward radiance after midnight.
- The figure would be 18 % (15–23 %) if the lights were not dimmed.
- Counting other operators' streetlights raises the two figures to 16 % and 21 %.

**What follows for Nocturne:**
- `vdl7/skyglow.py` carries DC's real light grid to six places through a single-scattering atmosphere.
- After midnight, Nocturne removes about **60 % of the streetlights' contribution** to the zenith sky at every place.
- Using Tucson's share as the prior, that moves the whole sky by only about **0.1 mag/arcsec²**: at Rock Creek Park, about 208 → 228 stars overhead.
- If the rest of the city's lighting halves after 23:00, the same place reaches about **421 stars**.
- This is why the Night Signal (`vdl7/nightsignal.py`) exists. The model's *reductions* in the streetlight term are robust. The absolute sky values depend on the prior until DC has its own sky-quality meters (`vdl7/observe.py`).

## 3. The problem is growing, and most people already cannot see the Milky Way

**Falchi et al. 2016**, *Science Advances* 2:e1600377:
- More than 80 % of the world's population, and more than 99 % of people in the U.S. and Europe, live under light-polluted skies.
- The Milky Way is hidden from more than a third of humanity, including nearly 80 % of North Americans.
- The authors warned that the LED transition could raise skyglow two- to three-fold unless colour and levels are handled carefully. DC's conversion to mostly 2700K has handled colour.

**Kyba, Altıntaş, Walker and Newhouse 2023**, *Science* 379:265–268, doi:10.1126/science.abq7781. From 51,351 citizen-science observations made between 2011 and 2022, the loss of visible stars corresponds to the sky brightening by **7–10 % per year** in the visible band. This is faster than satellites suggest. The authors put the gap down to changes in spectrum and emission angle, which satellites see poorly.

## 4. Health: colour and the bedroom window

**AMA 2016**, Council on Science and Public Health Report 2-A-16, adopted as Policy H-135.927:
- Encourages **3000K or lower** for outdoor roadway lighting, full shielding, and dimming in off-peak hours.
- The IES disputed the 3000K limit in 2017. Nocturne's spectral choices (2700K arterials, 2200K residential, PC-Amber at park edges) sit well inside the AMA guidance in any case.

**Brown et al. 2022**, *PLoS Biology* 20(3):e3001571. Consensus recommendations on melanopic EDI at the eye:
- At least **250 lx** by day.
- At most **10 lx** from 3 hours before bedtime.
- At most **1 lx** in the sleep environment.
- `nocturne trespass` reports melanopic EDI on the outside of the window against the 1 lx guide. Glass and curtains reduce what reaches the eye, so this screening errs on the safe side.

**CIE 150** limits on vertical illuminance at windows. Before / after curfew:

| Zone | Before curfew | After curfew |
|---|---|---|
| E1 | 2 lx | 0 lx (1 lx for public road lighting) |
| E2 | 5 lx | 1 lx |
| E3 | 10 lx | 2 lx |
| E4 | 25 lx | 5 lx |

These values are as reproduced in UK ILP GN01 and local-authority guidance. Check the CIE original before citing them in regulation.

## 5. Wildlife

**Van Doren et al. 2017**, *PNAS* 114(42):11175–11180, the New York Tribute in Light:
- One high-intensity installation drew migrating birds into its beams, at times concentrating them at densities up to about 150 times background, even in good visibility.
- When the lights went off, the birds **dispersed within minutes**.
- This reversibility is why migration nights (`EventKind.MIGRATION`, and the Night Signal's `migration` flag) work as an alert, not a season-long rule.

**Owens et al. 2020**, *Biological Conservation* 241:108259, doi:10.1016/j.biocon.2019.108259. Reviews evidence that artificial light at night drives insect declines through effects on development, movement, foraging, reproduction and predation. It also notes that light is one of the easier drivers to fix.

**Spectrum and birds.** Amber light is clearly better for insects and for melatonin. For birds, the evidence on colour is mixed, and intensity and upward light matter most. Migration nights therefore cut *intensity* (presence classes hold their 22:00 level; facades and empty office floors go dark) rather than changing colour.

## 6. Standards the code implements

| Standard | What the code does with it | Where |
|---|---|---|
| IES LM-63 | photometric files | `vdl7/photometry.py` |
| IES TM-15-11 Addendum A | BUG ratings; Tables A-1 to A-3 thresholds, checked against their reproduction in California's 2016 Title 24 and CALGreen | `vdl7/photometry.py` |
| IES RP-8 | road and pedestrian-conflict classes behind the floors | `vdl7/profiles.py` |
| IEEE 1003.1 POSIX TZ, RFC 8536 | the node's civil clock; matches the IANA database for all 498 zones, 2027–2030 | `vdl7/clock.py`, `tests/test_anycity.py` |
| NOAA solar position | dusk and dawn | `vdl7/clock.py` |
| Astronomical Almanac low-precision Moon | the Moon, checked against PyEphem at the 2026 eclipses | `vdl7/observe.py` |
| CIE S 026 | melanopic DER | `vdl7/spectral.py` |
| IDA/NSBM sky-brightness data format | sky-quality-meter logs | `vdl7/observe.py` |
| RFC 5545 iCalendar | the Night Signal as a calendar | `vdl7/nightsignal.py` |
