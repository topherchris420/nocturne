# DC streetlight inventory (aggregates)

`fleet.json` and `grid.csv` are reduced from the District's own streetlight
asset layer, so the business case and the skyglow model run on DC's real
fleet rather than assumed wattages.

- **Source:** DDOT / DC GIS, map service `DDOT/Streetlights`, layer 0
  "Streetlight" — <https://maps2.dcgis.dc.gov/dcgis/rest/services/DDOT/Streetlights/MapServer/0>.
  Published by the District of Columbia; reuse is subject to the District's
  open-data terms (opendata.dc.gov).
- **Retrieved:** see `retrieved` in `fleet.json`.
- **Regenerate:** `python tools/fetch_dc_inventory.py` (about 40 s).

Only aggregates are committed: counts, rated and commissioned watts by
Nocturne road class, CCT, ward, land use, shielding and smart-node
registration, and a ~550 m grid of lights and watts by class.

## How records map to Nocturne classes

| DC GIS | Nocturne class |
|---|---|
| Asset type *Alley Light* | alley |
| Asset type *Bike Trail Light* | park (trail / river edge) |
| Road classification *Principal* or *Minor Arterial* | arterial |
| *Interstate*, *Other Freeway and Expressway* | arterial (counted in `freeway_poles_in_arterial`) |
| *Collector* | collector |
| *Local*, or no classification | local |
| *Tunnel/Underpass*, *OHGS* (sign lighting), *Navigation*, *Tower* | kept static, not dimmed |

Only records with asset status *Active* are counted.

**Watts.** `rated_kw` sums the nameplate wattage of every luminaire on the
pole (`WATTAGE1`, plus `WATTAGE2` for the second and later luminaires when
given). `trimmed_kw` multiplies each pole by its commissioned maximum output
(`CLIGHT_DIMMING_1`, missing = 100 %). Trimmed watts are what the fleet draws
at full output today, so they are the baseline the business case uses.

**What the data says about DC today.** 97 % of active lights are LED, most of
them already 2700K; 96 % carry a registered networked node, so DC's lights
are already dimmable from a central system; and almost none are recorded with
a house-side shield.
