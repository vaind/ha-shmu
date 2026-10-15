"""Static catalogue of SHMÚ automatic weather stations (AWS).

SHMÚ's open-data server keys observations only by ``ind_kli`` (the station's
climatological/WMO index); it publishes no machine-readable station catalogue.
This table is therefore curated and hard-coded. It changes rarely, so shipping
it avoids fragile runtime scraping.

It lists every station that reports in the ``aws1min`` feed and can be placed
on a map: the 27 **synoptic** stations, which report the most (station
pressure, present weather, visibility), and ~70 further automatic stations,
most of which report temperature, humidity, wind and precipitation only.
``Station.synoptic`` tells the two apart.

Provenance — regenerate from these sources if the network changes:

* Synoptic stations, coordinates & elevation: "Zoznam synoptických staníc"
  https://www.shmu.sk/sk/?page=318  (official, exact values). Display names
  (correct Slovak diacritics): https://www.shmu.sk/sk/?id=meteo_apocasie_sk.
* Other stations, coordinates & names: the ``AWS2<ind_kli>`` entries of the
  marker array on https://www.shmu.sk/sk/?page=838&uhrny=24 (retrieved
  2026-10-15, 93 entries) — the same array, and the same recipe, as
  :mod:`shmu_opendata.gauges` uses for ``APS2``. Holíč (11800) is in the feed
  but not on that map; its coordinates come from WMO OSCAR (below).
* Other stations, elevation: WMO OSCAR/Surface, the WMO station registry SHMÚ
  reports its network to (``https://oscar.wmo.int/surface/rest/api/search/
  station?territoryName=SVK``, 78 records). A record is used only where its
  coordinates match the map entry exactly (they agree to six decimals); over
  the synoptic stations OSCAR agrees with ``?page=318`` to a median of 1 m.

Only stations present in the feed are listed (``?page=838`` also maps
Bratislava - Mlynská Dolina, 11810, which has not reported in 30 days), with
one exception: the synoptic Sliač (11903) has been missing from the feed for as
long, but stays because config entries refer to it. It is marked
``in_feed=False``, so it is not offered for new entries or picked as the
nearest station; existing entries still resolve it, and its entities stay
unavailable until SHMÚ publishes it again. The list is near-complete,
not total: Oravice (11919) and Jakubovany (11963) report but no source gives
their coordinates, so callers must tolerate a feed id that is not here.

Latitude/longitude are WGS84 degrees; elevation is metres above sea level, or
``None`` where no authoritative value exists (OSCAR does not register SHMÚ's
eastern regional stations). The ALADIN model terrain is **not** a substitute:
at the 68 stations with a known elevation it misses by a median 46 m and up to
777 m, i.e. tens of hPa once reduced to sea level, so a station with an
unknown elevation borrows a neighbour's sea-level pressure instead (see
:mod:`shmu_opendata.borrowing`).

Five stations' present-weather sensors report precipitation far more often
than it falls (measured against the radar composite and the stations' own
gauges, see AGENTS.md), so they are marked ``untrusted_precipitation_codes``
and the condition ladder ignores their precipitation codes
(:mod:`shmu_opendata.resolution`). The raw code is still published as is.
"""

from __future__ import annotations

from dataclasses import dataclass

from .distance import haversine_km


@dataclass(frozen=True, slots=True)
class Station:
    """A SHMÚ automatic weather station.

    ``ind_kli`` is the key used to look the station up in the open-data
    observation feed. ``elevation`` is ``None`` where no authoritative value is
    known (see the module docstring). ``synoptic`` marks the stations of the
    synoptic network, which report a fuller set of quantities. ``in_feed`` is
    ``False`` for a station kept only because existing entries refer to it
    while SHMÚ does not publish its observations.
    ``untrusted_precipitation_codes`` marks a present-weather sensor that
    reports precipitation codes far more often than it rains or snows;
    its "no significant weather" is still trusted.
    """

    ind_kli: int
    name: str
    latitude: float
    longitude: float
    elevation: float | None
    synoptic: bool = False
    in_feed: bool = True
    untrusted_precipitation_codes: bool = False

    def distance_km(self, latitude: float, longitude: float) -> float:
        """Great-circle distance in km from this station to a point."""
        return haversine_km(self.latitude, self.longitude, latitude, longitude)


# Ordered by ind_kli. See module docstring for provenance.
STATIONS: tuple[Station, ...] = (
    Station(11800, "Holíč", 48.818783, 17.176128, 170.0),
    Station(11803, "Trenčín", 48.866389, 17.999444, 204.0),
    Station(11805, "Senica - Kunov", 48.68915, 17.403094, 231.0),
    Station(11806, "Myjava", 48.753333, 17.560278, 345.0),
    Station(11812, "Malý Javorník", 48.2558, 17.1538, 586.0, synoptic=True),
    Station(11813, "Bratislava - Koliba", 48.1686, 17.1106, 286.0, synoptic=True),
    Station(11815, "Pezinok - Grinava", 48.272478, 17.245635, 144.0),
    Station(11816, "Bratislava - Letisko", 48.1717, 17.2, 131.0, synoptic=True),
    Station(11817, "Kráľová pri Senci", 48.198091, 17.513692, 123.0),
    Station(11818, "Gabčíkovo", 47.897736, 17.566213, 114.0),
    Station(11819, "Jaslovské Bohunice", 48.4867, 17.6708, 176.0, synoptic=True),
    Station(11820, "Žihárec", 48.070327, 17.881963, 112.0),
    Station(11826, "Piešťany", 48.6131, 17.8328, 163.0, synoptic=True),
    Station(11833, "Modra - Piesok", 48.372778, 17.273889, 533.0),
    Station(11835, "Moravský Svätý Ján", 48.581667, 16.994167, 155.0),
    Station(11838, "Kamanová", 48.470278, 18.102778, 154.0),
    Station(11839, "Uhrovec", 48.741415, 18.341417, 243.0),
    Station(11841, "Dolný Hričov", 49.2319, 18.6178, 309.0, synoptic=True),
    Station(11849, "Žikava", 48.458319, 18.388436, 319.0),
    Station(11855, "Nitra", 48.2806, 18.1356, 135.0, synoptic=True),
    Station(11856, "Mochovce", 48.2894, 18.4561, 261.0, synoptic=True),
    Station(
        11857,
        "Turzovka",
        49.401564,
        18.626783,
        496.0,
        untrusted_precipitation_codes=True,
    ),
    Station(11858, "Hurbanovo", 47.8733, 18.1944, 115.0, synoptic=True),
    Station(11862, "Beluša", 49.065833, 18.316389, 255.0),
    Station(11865, "Žilina-Vlčince", 49.211439, 18.771139, 358.0),
    Station(11866, "Čadca-Horelica", 49.430769, 18.809131, 420.0),
    Station(11867, "Prievidza", 48.7697, 18.5939, 260.0, synoptic=True),
    Station(11868, "Oravská Lesná", 49.367867, 19.182453, 781.0),
    Station(11869, "Rabča", 49.478717, 19.483603, 645.0),
    Station(11872, "Štiavnička (Ružomberok)", 49.071728, 19.34087, 507.0),
    Station(11874, "Liptovský Hrádok", 49.04033, 19.717285, 638.0),
    Station(11876, "Podbanské", 49.140056, 19.909004, 972.0),
    Station(
        11878,
        "Liptovský Mikuláš-Lipt. Ondrašová",
        49.09739,
        19.590288,
        569.0,
        untrusted_precipitation_codes=True,
    ),
    Station(11879, "Kremnické Bane", 48.734789, 18.908094, 764.0),
    Station(11880, "Dudince", 48.1692, 18.8761, 139.0, synoptic=True),
    Station(11881, "Želiezovce", 48.045833, 18.641111, 137.0),
    Station(11883, "Veľké Lovce", 48.056087, 18.335425, 186.0),
    Station(11884, "Mužla", 47.800456, 18.595672, 120.0),
    Station(11890, "Oravské Veselé", 49.471175, 19.383519, 757.0),
    Station(11892, "Oravský Podzámok", 49.262162, 19.369081, 530.0),
    Station(
        11893,
        "Žabokreky (pri Martine)",
        49.026686,
        18.922836,
        427.0,
        untrusted_precipitation_codes=True,
    ),
    Station(11894, "Donovaly", 48.8794, 19.2264, 992.0, synoptic=True),
    Station(11897, "Turčianske Teplice", 48.859067, 18.854947, 508.0),
    Station(
        11898,
        "Banská Bystrica",
        48.733419,
        19.115097,
        429.0,
        untrusted_precipitation_codes=True,
    ),
    Station(11900, "Žiar nad Hronom", 48.5861, 18.8522, 275.0, synoptic=True),
    Station(11901, "Banská Štiavnica", 48.449061, 18.919689, 570.0),
    Station(11902, "Bzovík", 48.318611, 19.0925, 353.0),
    # Sliač (11903): absent from aws1min since at least 2026-09-14, the oldest
    # day the ~32-day archive held on 2026-10-15; still on the shmu.sk table.
    Station(11903, "Sliač", 48.6425, 19.1419, 313.0, synoptic=True, in_feed=False),
    Station(11904, "Vígľaš - Pstruša", 48.543744, 19.320137, 368.0),
    Station(11905, "Dolné Plachtince", 48.203056, 19.311667, 192.0),
    Station(11908, "Liptovská Osada", 48.950556, 19.272222, 618.0),
    Station(11910, "Lom nad Rimavicou", 48.643889, 19.649167, 1017.0),
    Station(11916, "Chopok", 48.9439, 19.5922, 2005.0, synoptic=True),
    Station(11917, "Brezno", 48.800347, 19.636517, 488.0),
    Station(11918, "Liesek", 49.3694, 19.6794, 692.0, synoptic=True),
    Station(11926, "Málinec", 48.518275, 19.661455, 356.0),
    Station(11927, "Boľkovce", 48.3389, 19.7364, 214.0, synoptic=True),
    Station(11930, "Lomnický Štít", 49.1953, 20.215, 2635.0, synoptic=True),
    Station(11931, "Tatranská Lomnica - Skalnaté Pleso", 49.189444, 20.234167, 1778.0),
    Station(11933, "Štrbské Pleso", 49.1217, 20.0603, 1322.0, synoptic=True),
    Station(11934, "Poprad", 49.0689, 20.2456, 694.0, synoptic=True),
    Station(11935, "Tatranská Lomnica", 49.166389, 20.285278, 835.0),
    Station(11936, "Tatranská Javorina", 49.263889, 20.139444, None),
    Station(11938, "Telgárt", 48.8486, 20.1892, 901.0, synoptic=True),
    Station(11941, "Ratková", 48.5925, 20.091667, None),
    Station(11942, "Rimavská Sobota", 48.373611, 20.008611, None),
    Station(11944, "Rožňava", 48.652227, 20.535501, None),
    Station(11945, "Švedlár", 48.813205, 20.709754, None),
    Station(11946, "Štós - Kúpele", 48.718147, 20.795397, None),
    Station(11947, "Moldava nad Bodvou", 48.615076, 21.005117, None),
    Station(
        11949,
        "Spišské Vlachy",
        48.944197,
        20.80201,
        None,
        untrusted_precipitation_codes=True,
    ),
    Station(11950, "Podolínec", 49.262067, 20.542689, None),
    Station(11951, "Červený Kláštor", 49.387222, 20.4225, None),
    Station(11952, "Gánovce", 49.0333, 20.3167, 703.0, synoptic=True),
    Station(11953, "Revúca", 48.692943, 20.115013, None),
    Station(11957, "Stará Lesná", 49.15139, 20.289443, None),
    Station(11958, "Kojšovská hoľa", 48.7833, 20.9833, 1244.0, synoptic=True),
    Station(11959, "Tatranská Polianka", 49.121659, 20.185763, None),
    Station(11961, "Plaveč", 49.260129, 20.842235, None),
    Station(11962, "Bardejov", 49.285045, 21.270903, None),
    Station(11966, "Čaklov", 48.902778, 21.631389, None),
    Station(11967, "Zlatá Baňa", 48.949924, 21.420369, None),
    Station(11968, "Košice", 48.6722, 21.2225, 230.0, synoptic=True),
    Station(11969, "Košice - Podhradová", 48.753191, 21.245308, None),
    Station(11970, "Silica", 48.554924, 20.522989, None),
    Station(11974, "Roztoky", 49.396428, 21.492196, None),
    Station(11976, "Tisinec", 49.2156, 21.65, 216.0, synoptic=True),
    Station(11977, "Medzilaborce", 49.301648, 21.884013, None),
    Station(11978, "Trebišov", 48.6631, 21.7239, 105.0, synoptic=True),
    Station(11979, "Somotor", 48.390741, 21.806333, None),
    Station(11982, "Michalovce", 48.732222, 21.886111, None),
    Station(11984, "Orechová", 48.708594, 22.224087, None),
    Station(11992, "Osadné", 49.142222, 22.153333, None),
    Station(11993, "Kamenica nad Cirochou", 48.9389, 22.0061, 176.0, synoptic=True),
    Station(11995, "Vysoká nad Uhom", 48.63304, 22.1003, None),
)

STATIONS_BY_IND_KLI: dict[int, Station] = {s.ind_kli: s for s in STATIONS}


def get_station(ind_kli: int) -> Station | None:
    """Return the station with the given ``ind_kli``, or ``None``."""
    return STATIONS_BY_IND_KLI.get(ind_kli)


def nearest_station(latitude: float, longitude: float) -> Station:
    """Return the station closest to the given coordinates.

    Only stations SHMÚ currently publishes are considered: one with
    ``in_feed=False`` would never yield an observation.
    """
    return min(
        (s for s in STATIONS if s.in_feed),
        key=lambda s: s.distance_km(latitude, longitude),
    )
