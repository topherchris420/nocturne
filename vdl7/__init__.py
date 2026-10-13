"""VDL-7 reference firmware for Nocturne, the adaptive dark-sky lighting layer.

Spec: VD-DSL-SPEC-001 RevA (DC Dark-Sky Lighting Engineering Specification).

Modules
-------
clock       astronomical clock, US DST rule, RTC holdover, photocell debounce
profiles    road-class dimming profiles, phases, floors, tunable-white mix, bundle
security    Ed25519 signing (bench HMAC fallback) and canonical encoding
events      signed event store with monotonic TTLs
driver      DALI-2/D4i luminaire driver with system-failure level and NC relay
controller  the 1 Hz control loop, mode ladder, arbitration, slew, CLO, SAFE mode
mesh        Wi-SUN segment mesh: gateway reachability, light carpet, flood relay
spectral    LED spectra, Rayleigh/scotopic skyglow factors, melanopic DER
"""

__version__ = "0.1.0"
