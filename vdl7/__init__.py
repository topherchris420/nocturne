"""Nocturne: the VDL-7 dark-sky streetlight firmware and the city tools around it.

Spec: VD-DSL-SPEC-001 RevA (DC Dark-Sky Lighting Engineering Specification).

The node
--------
clock        astronomical clock, POSIX TZ rule engine (any city), RTC holdover, photocell debounce
sites        city presets: latitude, longitude, compiled-in TZ rule
profiles     road-class dimming profiles, phases, floors, zone overlays, tunable-white mix, bundle
security     Ed25519 signing (bench HMAC fallback) and canonical encoding
events       signed event store with monotonic TTLs
driver       DALI-2/D4i luminaire driver with system-failure level and NC relay
controller   the 1 Hz control loop, mode ladder, arbitration, slew, CLO, SAFE mode
mesh         Wi-SUN segment mesh: gateway reachability, light carpet, flood relay
spectral     LED spectra, Rayleigh/scotopic skyglow factors, melanopic DER

The city
--------
annual       a year of nights for a whole fleet: energy, cost, carbon, light, skyglow
skyglow      zenith sky brightness, naked-eye limit and stars at named places
photometry   IES LM-63 files, TM-15-11 BUG ratings, window trespass
nightsignal  the signed public curfew feed for every light in the city
observe      the Moon, sky-quality-meter logs, curfew-step verification
pilot        randomised stepped-wedge rollout with a safety brake
demand       traffic and pedestrian curves (Section 6.4)
schedule     Phase 0 programmes for the networked nodes a city already has
integration  controller capability checks (brighter-only), the readiness record, CMS readback

Restoration
-----------
restore      least-cost multi-owner plans against sky-brightness targets: ranges, per-place effects, interactions
derive       a project's coefficients from emitter geometry, atmosphere and surfaces
attribution  preregistered source-isolation trials and their analysis
app          the planner in a local browser page (`nocturne app`)
"""

__version__ = "1.0.0"
