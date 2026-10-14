"""Where a node is: latitude, longitude and the POSIX TZ rule it compiles in.

Washington, DC is the reference deployment. The others are here so the same
firmware, tests and business case run unchanged for any city: dark-sky
leaders (Flagstaff, Tucson), large US fleets, Europe (where France already
legislates curfews), the southern hemisphere (Sydney, Adelaide's half-hour
offset, Auckland), and two cities past 64 N where the sun stays up or down
all night (Reykjavik, Tromso). Each rule matches the TZif footer the IANA
database compiles for the zone; EXT-CLK-4 checks every one against
`zoneinfo` for 2024-2030.

Coordinates are city-centre approximations. A real node is commissioned with
its own pole's position.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .clock import DC_LAT, DC_LON, POSIX_TZ, parse_posix_tz


@dataclass(frozen=True)
class Site:
    key: str
    name: str
    lat: float
    lon: float
    tz: str          # POSIX rule compiled into the node
    iana: str        # the zone it was compiled from (commissioning and tests only)

    def __post_init__(self):
        parse_posix_tz(self.tz)


SITES: Dict[str, Site] = {s.key: s for s in [
    Site("dc", "Washington, DC", DC_LAT, DC_LON, POSIX_TZ, "America/New_York"),
    Site("nyc", "New York, NY", 40.7128, -74.0060, "EST5EDT,M3.2.0,M11.1.0", "America/New_York"),
    Site("chicago", "Chicago, IL", 41.8781, -87.6298, "CST6CDT,M3.2.0,M11.1.0", "America/Chicago"),
    Site("tucson", "Tucson, AZ", 32.2226, -110.9747, "MST7", "America/Phoenix"),
    Site("flagstaff", "Flagstaff, AZ", 35.1983, -111.6513, "MST7", "America/Phoenix"),
    Site("la", "Los Angeles, CA", 34.0522, -118.2437, "PST8PDT,M3.2.0,M11.1.0", "America/Los_Angeles"),
    Site("anchorage", "Anchorage, AK", 61.2181, -149.9003, "AKST9AKDT,M3.2.0,M11.1.0", "America/Anchorage"),
    Site("honolulu", "Honolulu, HI", 21.3069, -157.8583, "HST10", "Pacific/Honolulu"),
    Site("london", "London, UK", 51.5074, -0.1278, "GMT0BST,M3.5.0/1,M10.5.0", "Europe/London"),
    Site("paris", "Paris, France", 48.8566, 2.3522, "CET-1CEST,M3.5.0,M10.5.0/3", "Europe/Paris"),
    Site("reykjavik", "Reykjavik, Iceland", 64.1466, -21.9426, "GMT0", "Atlantic/Reykjavik"),
    Site("tromso", "Tromso, Norway", 69.6492, 18.9553, "CET-1CEST,M3.5.0,M10.5.0/3", "Europe/Oslo"),
    Site("sydney", "Sydney, Australia", -33.8688, 151.2093, "AEST-10AEDT,M10.1.0,M4.1.0/3", "Australia/Sydney"),
    Site("adelaide", "Adelaide, Australia", -34.9285, 138.6007, "ACST-9:30ACDT,M10.1.0,M4.1.0/3", "Australia/Adelaide"),
    Site("auckland", "Auckland, New Zealand", -36.8485, 174.7633, "NZST-12NZDT,M9.5.0,M4.1.0/3", "Pacific/Auckland"),
    Site("santiago", "Santiago, Chile", -33.4489, -70.6693, "<-04>4<-03>,M9.1.6/24,M4.1.6/24", "America/Santiago"),
    Site("tehran", "Tehran, Iran", 35.6892, 51.3890, "<+0330>-3:30", "Asia/Tehran"),
]}

DEFAULT_SITE = SITES["dc"]


def site(key: str) -> Site:
    try:
        return SITES[key]
    except KeyError:
        raise KeyError(f"unknown site {key!r}; known: {', '.join(SITES)}") from None
