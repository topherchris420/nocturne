# Nocturne night simulation: results

Night of 2026-10-13 18:00 to 2026-10-14 08:00 local; 4 streets x 20 poles per class, 30 m spacing; scaled to 75,000 lights.

| Scenario | Energy vs today | Spec 6.3 | Delivered light vs today | Spec 6.3 | Skyglow index | MWh / night |
|---|---|---|---|---|---|---|
| Today: static 100 %, current CCT | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 55.6 |
| Adaptive dimming only | 0.669 | 0.65 | 0.671 | 0.65 | 0.674 | 37.19 |
| + U0 optics | 0.669 | 0.65 | 0.671 | 0.65 | 0.539 | 37.19 |
| + warm spectrum (full Nocturne) | 0.729 | 0.7 | 0.671 | 0.65 | 0.487 | 40.51 |
| Full Nocturne during a 7-hour carrier outage | 0.704 | 0.68 | 0.648 | 0.63 | 0.47 | 39.12 |
| Same hardware, cloud-dependent control, same outage | 1.022 | 1.0 | 0.95 | 0.92 | 0.695 | 56.84 |
| Full Nocturne with a CAD incident on one local street 00:40-01:40 | 0.733 |  | 0.675 |  | 0.49 | 40.73 |
| Full Nocturne with rain 23:00-02:00 | 0.771 |  | 0.709 |  | 0.513 | 42.88 |
| Full Nocturne on a forecast heavy-migration night | 0.71 |  | 0.654 |  | 0.475 | 39.48 |

## Skyglow waterfall (upward flux x Rayleigh, today = 1.00)

- Today: 1.000
- Adaptive dimming: 0.674 (-0.326)
- U0 optics: 0.539 (-0.135)
- Warm spectrum: 0.487 (-0.052)

Saving vs the static baseline: 15.09 MWh per night, about 5.51 GWh a year (October night x 365).

## Spectral metrics (per photopic lumen, 4000K = 1.00)

| Spectrum | CCT | Duv | Rayleigh | Skyglow (scotopic) | Mie | mel-DER | <500 nm |
|---|---|---|---|---|---|---|---|
| 4000K | 4013 | +0.0006 | 1.00 | 1.00 | 1.00 | 0.61 | 22.0% |
| 3000K | 3012 | +0.0010 | 0.86 | 0.77 | 0.95 | 0.45 | 14.4% |
| 2700K | 2702 | +0.0011 | 0.82 | 0.68 | 0.94 | 0.39 | 11.8% |
| 2200K | 2197 | -0.0009 | 0.73 | 0.47 | 0.91 | 0.26 | 6.8% |
| PC-Amber | 1853 | +0.0080 | 0.54 | 0.17 | 0.73 | 0.06 | 0.5% |
| Narrow-band amber | 1802 | +0.0088 | 0.44 | 0.07 | 0.59 | 0.01 | 0.0% |

## Mode share by class (fraction of node-steps)

- today: arterial {'STATIC': 1.0}; collector {'STATIC': 1.0}; local {'STATIC': 1.0}; alley {'STATIC': 1.0}; park {'STATIC': 1.0}
- dimming: arterial {'ONLINE': 1.0}; collector {'ONLINE': 1.0}; local {'ONLINE': 1.0}; alley {'ONLINE': 1.0}; park {'ONLINE': 1.0}
- dimming_u0: arterial {'ONLINE': 1.0}; collector {'ONLINE': 1.0}; local {'ONLINE': 1.0}; alley {'ONLINE': 1.0}; park {'ONLINE': 1.0}
- nocturne: arterial {'ONLINE': 1.0}; collector {'ONLINE': 1.0}; local {'ONLINE': 1.0}; alley {'ONLINE': 1.0}; park {'ONLINE': 1.0}
- outage: arterial {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}; collector {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}; local {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}; alley {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}; park {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}
- legacy_outage: arterial {'LOST_COMMS_100%': 0.5, 'ONLINE': 0.5}; collector {'LOST_COMMS_100%': 0.5, 'ONLINE': 0.5}; local {'LOST_COMMS_100%': 0.5, 'ONLINE': 0.5}; alley {'LOST_COMMS_100%': 0.5, 'ONLINE': 0.5}; park {'LOST_COMMS_100%': 0.5, 'ONLINE': 0.5}
- emergency: arterial {'ONLINE': 1.0}; collector {'ONLINE': 1.0}; local {'ONLINE': 1.0}; alley {'ONLINE': 1.0}; park {'ONLINE': 1.0}
- rain: arterial {'ONLINE': 1.0}; collector {'ONLINE': 1.0}; local {'ONLINE': 1.0}; alley {'ONLINE': 1.0}; park {'ONLINE': 1.0}
- migration: arterial {'ONLINE': 1.0}; collector {'ONLINE': 1.0}; local {'ONLINE': 1.0}; alley {'ONLINE': 1.0}; park {'ONLINE': 1.0}
