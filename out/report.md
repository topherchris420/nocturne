# Nocturne night simulation: results

Night of 2026-10-13 18:00 to 2026-10-14 08:00 local, 75,000 lights scaled from 20 poles per class.

| Scenario | Energy vs today | Delivered light vs today | Skyglow index | MWh / night |
|---|---|---|---|---|
| Today: static 100 %, current CCT | 1.0 | 1.0 | 1.0 | 55.6 |
| Adaptive dimming only | 0.665 | 0.667 | 0.67 | 36.96 |
| + U0 optics | 0.665 | 0.667 | 0.536 | 36.96 |
| + warm spectrum (full Nocturne) | 0.723 | 0.667 | 0.484 | 40.22 |
| Full Nocturne during a 7-hour carrier outage | 0.697 | 0.643 | 0.467 | 38.78 |
| Cloud-dependent nodes in the same outage | 0.941 | 0.942 | 0.944 | 52.33 |
| Full Nocturne with a CAD incident on the local street 00:40-01:40 | 0.73 | 0.673 | 0.489 | 40.59 |
| Full Nocturne with rain 23:00-02:00 | 0.766 | 0.704 | 0.511 | 42.57 |

## Skyglow waterfall (upward flux x Rayleigh, today = 1.00)

- Today: 1.000
- Adaptive dimming: 0.670 (-0.330)
- U0 optics: 0.536 (-0.134)
- Warm spectrum: 0.484 (-0.052)
- Full Nocturne: 0.484

Annual energy saving vs the static baseline: about 5.61 GWh (October night x 365).

## Spectral metrics (per photopic lumen, 4000K = 1.00)

| Spectrum | CCT | Duv | Rayleigh | Skyglow (scotopic) | Mie | mel-DER | <500 nm |
|---|---|---|---|---|---|---|---|
| 4000K | 4013 | +0.0006 | 1.00 | 1.00 | 1.00 | 0.61 | 22.0% |
| 3000K | 3012 | +0.0010 | 0.86 | 0.77 | 0.95 | 0.45 | 14.4% |
| 2700K | 2702 | +0.0011 | 0.82 | 0.68 | 0.94 | 0.39 | 11.8% |
| 2200K | 2197 | -0.0009 | 0.73 | 0.47 | 0.91 | 0.26 | 6.8% |
| PC-Amber | 1853 | +0.0080 | 0.54 | 0.17 | 0.73 | 0.06 | 0.5% |
| Narrow-band amber | 1802 | +0.0088 | 0.44 | 0.07 | 0.59 | 0.01 | 0.0% |

## Mode share by class (fraction of simulation steps)

- today: arterial {'STATIC': 1.0}; collector {'STATIC': 1.0}; local {'STATIC': 1.0}; alley {'STATIC': 1.0}; park {'STATIC': 1.0}
- dimming: arterial {'ONLINE': 1.0}; collector {'ONLINE': 1.0}; local {'ONLINE': 1.0}; alley {'ONLINE': 1.0}; park {'ONLINE': 1.0}
- dimming_u0: arterial {'ONLINE': 1.0}; collector {'ONLINE': 1.0}; local {'ONLINE': 1.0}; alley {'ONLINE': 1.0}; park {'ONLINE': 1.0}
- nocturne: arterial {'ONLINE': 1.0}; collector {'ONLINE': 1.0}; local {'ONLINE': 1.0}; alley {'ONLINE': 1.0}; park {'ONLINE': 1.0}
- outage: arterial {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}; collector {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}; local {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}; alley {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}; park {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}
- legacy_outage: arterial {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}; collector {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}; local {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}; alley {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}; park {'AUTONOMOUS': 0.482, 'MESH': 0.018, 'ONLINE': 0.5}
- emergency: arterial {'ONLINE': 1.0}; collector {'ONLINE': 1.0}; local {'ONLINE': 1.0}; alley {'ONLINE': 1.0}; park {'ONLINE': 1.0}
- rain: arterial {'ONLINE': 1.0}; collector {'ONLINE': 1.0}; local {'ONLINE': 1.0}; alley {'ONLINE': 1.0}; park {'ONLINE': 1.0}
