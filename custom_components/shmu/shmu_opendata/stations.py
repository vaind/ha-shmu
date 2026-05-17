"""Static catalogue of SHMÚ synoptic weather stations.

SHMÚ's open-data server keys observations only by ``ind_kli`` (the station's
climatological/WMO index); it publishes no machine-readable station catalogue.
This table is therefore curated and hard-coded. It changes very rarely (the
synoptic network is stable), so shipping it avoids fragile runtime scraping.

Provenance — regenerate from these two authoritative SHMÚ pages if the network
changes:

* Coordinates & elevation: "Zoznam synoptických staníc"
  https://www.shmu.sk/sk/?page=318  (official, exact values)
* Display names (correct Slovak diacritics): "Aktuálne počasie - tabuľka"
  https://www.shmu.sk/sk/?id=meteo_apocasie_sk&page=1

Latitude/longitude are WGS84 degrees; elevation is metres above sea level.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

_EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True, slots=True)
class Station:
    """A SHMÚ synoptic station.

    ``ind_kli`` is the key used to look the station up in the open-data
    observation feed.
    """

    ind_kli: int
    name: str
    latitude: float
    longitude: float
    elevation: float

    def distance_km(self, latitude: float, longitude: float) -> float:
        """Great-circle distance in km from this station to a point."""
        d_lat = radians(latitude - self.latitude)
        d_lon = radians(longitude - self.longitude)
        a = (
            sin(d_lat / 2) ** 2
            + cos(radians(self.latitude)) * cos(radians(latitude)) * sin(d_lon / 2) ** 2
        )
        return 2 * _EARTH_RADIUS_KM * asin(sqrt(a))


# Ordered by ind_kli. See module docstring for provenance.
STATIONS: tuple[Station, ...] = (
    Station(11812, "Malý Javorník", 48.2558, 17.1538, 586.0),
    Station(11813, "Bratislava - Koliba", 48.1686, 17.1106, 286.0),
    Station(11816, "Bratislava - Letisko", 48.1717, 17.2, 131.0),
    Station(11819, "Jaslovské Bohunice", 48.4867, 17.6708, 176.0),
    Station(11826, "Piešťany", 48.6131, 17.8328, 163.0),
    Station(11841, "Dolný Hričov", 49.2319, 18.6178, 309.0),
    Station(11855, "Nitra", 48.2806, 18.1356, 135.0),
    Station(11856, "Mochovce", 48.2894, 18.4561, 261.0),
    Station(11858, "Hurbanovo", 47.8733, 18.1944, 115.0),
    Station(11867, "Prievidza", 48.7697, 18.5939, 260.0),
    Station(11880, "Dudince", 48.1692, 18.8761, 139.0),
    Station(11894, "Donovaly", 48.8794, 19.2264, 992.0),
    Station(11900, "Žiar nad Hronom", 48.5861, 18.8522, 275.0),
    Station(11903, "Sliač", 48.6425, 19.1419, 313.0),
    Station(11916, "Chopok", 48.9439, 19.5922, 2005.0),
    Station(11918, "Liesek", 49.3694, 19.6794, 692.0),
    Station(11927, "Boľkovce", 48.3389, 19.7364, 214.0),
    Station(11930, "Lomnický Štít", 49.1953, 20.215, 2635.0),
    Station(11933, "Štrbské Pleso", 49.1217, 20.0603, 1322.0),
    Station(11934, "Poprad", 49.0689, 20.2456, 694.0),
    Station(11938, "Telgárt", 48.8486, 20.1892, 901.0),
    Station(11952, "Gánovce", 49.0333, 20.3167, 703.0),
    Station(11958, "Kojšovská hoľa", 48.7833, 20.9833, 1244.0),
    Station(11968, "Košice", 48.6722, 21.2225, 230.0),
    Station(11976, "Tisinec", 49.2156, 21.65, 216.0),
    Station(11978, "Trebišov", 48.6631, 21.7239, 105.0),
    Station(11993, "Kamenica nad Cirochou", 48.9389, 22.0061, 176.0),
)

STATIONS_BY_IND_KLI: dict[int, Station] = {s.ind_kli: s for s in STATIONS}


def get_station(ind_kli: int) -> Station | None:
    """Return the station with the given ``ind_kli``, or ``None``."""
    return STATIONS_BY_IND_KLI.get(ind_kli)


def nearest_station(latitude: float, longitude: float) -> Station:
    """Return the synoptic station closest to the given coordinates."""
    return min(STATIONS, key=lambda s: s.distance_km(latitude, longitude))
