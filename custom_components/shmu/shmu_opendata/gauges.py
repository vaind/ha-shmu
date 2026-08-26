"""Static catalogue of SHMÚ automatic rain-gauge stations.

The ``aps1min`` precipitation feed keys its records by ``ind_zra``, an id
space **completely disjoint** from the ``ind_kli`` of the synoptic stations in
:mod:`shmu_opendata.stations` — this is a second, complementary network of
~190 gauges, roughly three times as dense as the 27 synoptic stations.

As with the synoptic catalogue, SHMÚ publishes no machine-readable station
list, so this table is curated and hard-coded. Two routes were checked and are
dead ends (verified 2026-08-26, so nobody repeats the search):

* the INSPIRE record linked from ``precipitation/`` on the open-data server
  (``rpi.gov.sk/…/dfa31b86-69b4-45b8-988f-0e07b80f01c8``) — a ``GetRecordById``
  against the RPI CSW returns an *empty* response; the record is not indexed;
* the national open-data catalogue entry named in ``aps1min_metadata.json``
  (``data.slovensko.sk/datasety/34c1c3ae-…``) — one distribution only, the
  JSON feed itself.

Provenance — regenerate from the SHMÚ page that plots the gauges on a map
(retrieved 2026-08-26, 190 entries). The page embeds the marker list as an
inline JS array; ``uid`` carries the network prefix and the id::

    # https://www.shmu.sk/sk/?page=838&uhrny=24
    #   uhrny=24 lists the most gauges (the shorter windows list fewer);
    #   the coordinates are identical across all uhrny values.
    array = re.search(r"(?s)var\\s+stations\\s*=\\s*(\\[.*?\\]);", html).group(1)
    ENTRY = re.compile(
        r"\\{nazov:'((?:[^'\\\\]|\\\\.)*)',lat:([-\\d.]+),lon:([-\\d.]+),"
        r"ids:'[^']*',value:'[^']*',uid:'APS2(\\d+)'\\}"
    )
    # nazov is "<ind_zra> - <name>": split on the FIRST " - " (names contain
    # it too, e.g. "Rakúske lúky - horáreň Fľak") and strip (one has a
    # trailing space). AWS2/AHS entries are other networks — keep only APS2.

The same array carries the synoptic stations as ``AWS2<ind_kli>``, which is
how these coordinates were validated: over the 24 stations also present in
:mod:`shmu_opendata.stations` (curated from a different SHMÚ page) the two
sources agree to a median of 272 m, worst case 1.2 km — far below the ~16 km
spacing of this network.

The catalogue is near-complete, not total: sampling the feed across its
32-day archive found 197 distinct ``ind_zra``, of which these 190 are listed
by the map page. Callers must therefore tolerate an id in the feed that is
absent here.

Latitude/longitude are WGS84 degrees. SHMÚ publishes no elevation for these
gauges — unlike synoptic stations they report no pressure, so none is needed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .distance import haversine_km


@dataclass(frozen=True, slots=True)
class Gauge:
    """A SHMÚ automatic rain-gauge station.

    ``ind_zra`` is the key used to look the gauge up in the open-data
    ``aps1min`` precipitation feed.
    """

    ind_zra: int
    name: str
    latitude: float
    longitude: float

    def distance_km(self, latitude: float, longitude: float) -> float:
        """Great-circle distance in km from this gauge to a point."""
        return haversine_km(self.latitude, self.longitude, latitude, longitude)


# Ordered by ind_zra. See module docstring for provenance.
GAUGES: tuple[Gauge, ...] = (
    Gauge(11060, "Osturňa", 49.335995, 20.260832),
    Gauge(11080, "Reľov", 49.295863, 20.380594),
    Gauge(12180, "Kežmarok", 49.139122, 20.439928),
    Gauge(13020, "Rakúske lúky - horáreň Fľak", 49.21, 20.326389),
    Gauge(13120, "Ihľany-Majerka", 49.181814, 20.545369),
    Gauge(13155, "Jarabina", 49.334167, 20.657778),
    Gauge(13180, "Jakubany", 49.239722, 20.692778),
    Gauge(14020, "Radošovce", 48.775993, 17.279141),
    Gauge(14040, "Skalica", 48.844167, 17.221111),
    Gauge(15060, "Brezová pod Bradlom", 48.66252, 17.538046),
    Gauge(15080, "Jablonica", 48.606908, 17.423733),
    Gauge(15100, "Vrbovce", 48.811176, 17.465972),
    Gauge(15155, "Smrdáky", 48.722302, 17.304986),
    Gauge(15200, "Šaštín - Stráže", 48.635042, 17.1413),
    Gauge(16020, "Plavecký Peter", 48.537597, 17.326191),
    Gauge(16040, "Sološnica", 48.468889, 17.222778),
    Gauge(16160, "Malacky", 48.439867, 17.006386),
    Gauge(16180, "Pernek", 48.363056, 17.154722),
    Gauge(17140, "Bratislava - Koliba", 48.16778, 17.10583),
    Gauge(17490, "Blahová", 48.088333, 17.544167),
    Gauge(17720, "Kolárovo", 47.94008, 17.953813),
    Gauge(18220, "Dobrá Voda", 48.594444, 17.535833),
    Gauge(18320, "Smolenice", 48.5025, 17.420556),
    Gauge(18380, "Biely Kostol", 48.366667, 17.537222),
    Gauge(18440, "Častá", 48.399167, 17.353611),
    Gauge(18480, "Sládkovičovo", 48.20074, 17.6275),
    Gauge(18540, "Siladice", 48.36313, 17.74582),
    Gauge(19120, "Gbelce", 47.847621, 18.523629),
    Gauge(20020, "Liptovská Teplička", 48.965857, 20.085393),
    Gauge(20040, "VN Čierny Váh", 49.015881, 19.933152),
    Gauge(20160, "Vyšná Boca", 48.928044, 19.753854),
    Gauge(21120, "Demänovská Dolina - Jasná", 48.965638, 19.585273),
    Gauge(21180, "Huty", 49.21899, 19.563172),
    Gauge(21240, "Partizánska Ľupča - Magurka", 48.944722, 19.432778),
    Gauge(21460, "Ľubochňa", 49.1206, 19.172966),
    Gauge(22043, "Novoť", 49.427895, 19.268045),
    Gauge(22080, "Mútne", 49.460345, 19.322385),
    Gauge(22120, "Lokca", 49.3706, 19.411494),
    Gauge(22170, "Oravská Polhora", 49.552222, 19.421667),
    Gauge(22240, "Suchá Hora", 49.364705, 19.778466),
    Gauge(23060, "Oravice", 49.2825, 19.756111),
    Gauge(23140, "Zuberec", 49.259667, 19.615555),
    Gauge(23260, "Párnica", 49.193754, 19.195647),
    Gauge(23280, "Zázrivá", 49.275082, 19.151743),
    Gauge(24040, "Turčianska Štiavnička", 49.09065, 19.025094),
    Gauge(24080, "Turček", 48.764228, 18.935214),
    Gauge(24180, "Kláštor pod Znievom", 48.973889, 18.808889),
    Gauge(24200, "Blatnica", 48.935675, 18.923986),
    Gauge(24295, "Martinské hole", 49.094456, 18.835114),
    Gauge(24320, "Terchová - Vrátna dolina", 49.232147, 19.061103),
    Gauge(25060, "Makov", 49.372644, 18.491159),
    Gauge(25140, "Skalité", 49.495383, 18.897214),
    Gauge(25180, "Stará Bystrica", 49.34528, 18.9375),
    Gauge(25220, "Horný Vadičov", 49.278039, 18.896806),
    Gauge(25260, "Nesluša", 49.314233, 18.744906),
    Gauge(25280, "Rajecká Lesná", 49.045586, 18.622472),
    Gauge(25340, "Stránske", 49.115428, 18.704106),
    Gauge(26140, "Brvnište", 49.212222, 18.428889),
    Gauge(26210, "Považská Bystrica-Kúnovec", 49.095508, 18.410197),
    Gauge(26260, "Lazy pod Makytou", 49.261667, 18.218889),
    Gauge(27020, "Pružina", 49.018611, 18.477222),
    Gauge(27080, "Zubák", 49.149167, 18.212222),
    Gauge(27120, "Horné Srnie", 48.993333, 18.093333),
    Gauge(27140, "Horná Súča", 48.970859, 17.978577),
    Gauge(27180, "Košecké Podhradie", 48.979343, 18.299679),
    Gauge(28020, "Bošáca-Zabudišová", 48.864722, 17.837222),
    Gauge(28060, "Lubina-Hrnčiarové", 48.816764, 17.702597),
    Gauge(28120, "Selec", 48.794703, 17.989141),
    Gauge(28180, "Krajné", 48.703889, 17.685556),
    Gauge(30040, "Chvojnica", 48.88, 18.561944),
    Gauge(30100, "Ráztočno", 48.773056, 18.756667),
    Gauge(30160, "Bystričany", 48.657594, 18.513186),
    Gauge(30200, "Valaská Belá", 48.888889, 18.396389),
    Gauge(30240, "Zliechov", 48.954167, 18.433889),
    Gauge(30260, "Nitrianske Rudno", 48.799444, 18.4725),
    Gauge(30360, "Šípkov", 48.852622, 18.296943),
    Gauge(30400, "Motešice", 48.830278, 18.186111),
    Gauge(30520, "Zlatníky", 48.71139, 18.12417),
    Gauge(30560, "Nedašovce", 48.666111, 18.315556),
    Gauge(31140, "Horné Lefantovce", 48.424225, 18.144301),
    Gauge(31160, "Radošina", 48.549406, 17.930597),
    Gauge(31420, "Lehota", 48.312222, 17.982778),
    Gauge(31500, "Rastislavice", 48.136586, 18.075415),
    Gauge(32020, "Malá Lehota", 48.498524, 18.569489),
    Gauge(32100, "Skýcov", 48.504164, 18.421005),
    Gauge(32140, "Zlatno", 48.46533, 18.312971),
    Gauge(32160, "Tesárske Mlyňany", 48.323333, 18.368611),
    Gauge(33060, "Pohorelá", 48.861107, 20.018577),
    Gauge(33120, "Polomka", 48.849458, 19.856354),
    Gauge(33160, "Pohronská Polhora", 48.754167, 19.801111),
    Gauge(33217, "Čierny Balog - Dobroč", 48.730961, 19.697868),
    Gauge(34020, "Jarabá", 48.889656, 19.688789),
    Gauge(34070, "Jasenie", 48.853869, 19.455931),
    Gauge(34090, "Chata pod Hrbom", 48.736903, 19.45385),
    Gauge(34120, "Slovenská Ľupča", 48.764673, 19.275533),
    Gauge(34160, "Dolný Harmanec", 48.807378, 19.054614),
    Gauge(34180, "Motyčky", 48.860178, 19.171817),
    Gauge(34280, "Králiky", 48.738307, 19.041103),
    Gauge(35060, "Detvianska Huta", 48.572222, 19.602222),
    Gauge(35080, "Poľana (Očová-Pajta)", 48.625161, 19.385951),
    Gauge(35180, "Hrochoť", 48.657702, 19.318445),
    Gauge(35240, "Dobrá Niva", 48.482242, 19.080342),
    Gauge(36060, "Močiar", 48.539528, 18.950961),
    Gauge(36140, "Handlová - Nová Lehota", 48.682614, 18.735523),
    Gauge(36200, "Sklené Teplice", 48.5325, 18.862861),
    Gauge(36280, "Kľak", 48.582386, 18.641067),
    Gauge(36340, "Žarnovica", 48.471617, 18.725058),
    Gauge(36380, "Hronský Beňadik", 48.350736, 18.566754),
    Gauge(37060, "Pukanec", 48.355256, 18.725141),
    Gauge(37120, "Žemberovce", 48.263791, 18.742341),
    Gauge(37140, "Levice", 48.216332, 18.616624),
    Gauge(37260, "Farná", 48.005278, 18.508333),
    Gauge(37340, "Kamenica nad Hronom", 47.827222, 18.735556),
    Gauge(38080, "Cinobaňa", 48.443794, 19.654264),
    Gauge(38140, "Ožďany", 48.378217, 19.890958),
    Gauge(39020, "Lipovany", 48.221587, 19.70891),
    Gauge(39060, "Horný Tisovník", 48.415278, 19.362778),
    Gauge(39120, "Ľuboreč", 48.313791, 19.511416),
    Gauge(39160, "Bušince", 48.174012, 19.49657),
    Gauge(39190, "Stredné Plachtince - Španí Laz", 48.240278, 19.257222),
    Gauge(40080, "Čelovce", 48.184696, 19.143996),
    Gauge(40220, "Senohrad", 48.358325, 19.195825),
    Gauge(40320, "Ladzany", 48.263813, 18.906678),
    Gauge(40480, "Lontov", 48.040833, 18.776389),
    Gauge(41020, "Veľké Trakany", 48.393845, 22.082999),
    Gauge(43020, "Habura", 49.322263, 21.861122),
    Gauge(43220, "Papín", 49.09317, 22.0597),
    Gauge(43320, "Starina", 49.0425, 22.26),
    Gauge(43380, "Zemplínske Hámre", 48.952778, 22.148611),
    Gauge(44040, "Strážske", 48.87667, 21.83667),
    Gauge(45040, "Kolbasov", 49.003889, 22.3875),
    Gauge(45060, "Zboj", 49.026751, 22.487038),
    Gauge(45100, "Klenová", 48.940278, 22.333889),
    Gauge(46080, "Remetské Hámre", 48.855752, 22.18749),
    Gauge(46120, "Podhoroď", 48.81841, 22.299703),
    Gauge(47060, "Budkovce", 48.630833, 21.93),
    Gauge(48020, "Nižná Polianka", 49.403893, 21.402674),
    Gauge(48060, "Nižný Komárnik", 49.373599, 21.696295),
    Gauge(48100, "Dlhoňa", 49.400278, 21.571111),
    Gauge(48180, "Turany nad Ondavou", 49.096423, 21.656906),
    Gauge(48200, "Slovenská Kajňa", 48.965, 21.701389),
    Gauge(48220, "Oľka", 49.159444, 21.843333),
    Gauge(49040, "Malcov", 49.307328, 21.068135),
    Gauge(49080, "Cigeľka", 49.41232, 21.146693),
    Gauge(49140, "Regetovka", 49.42267, 21.270185),
    Gauge(49200, "Kurimka", 49.318056, 21.437222),
    Gauge(49260, "Kuková", 49.110545, 21.4518),
    Gauge(49280, "Okrúhle", 49.180723, 21.555129),
    Gauge(49320, "Hanušovce nad Topľou", 49.0365, 21.515822),
    Gauge(49420, "Banské", 48.831453, 21.568858),
    Gauge(50040, "Dargov", 48.731787, 21.589365),
    Gauge(50140, "Hraň", 48.545, 21.8025),
    Gauge(51160, "Slanská Huta", 48.5975, 21.467222),
    Gauge(51180, "Michaľany", 48.517801, 21.626362),
    Gauge(52020, "Vyšná Slaná", 48.787912, 20.314135),
    Gauge(52220, "Slavošovce", 48.714404, 20.27827),
    Gauge(52260, "Kunova Teplica", 48.611024, 20.382661),
    Gauge(53040, "Muránska Huta - Predná Hora", 48.768586, 20.104758),
    Gauge(53095, "Muránska Zdychava-lazy", 48.746072, 20.126236),
    Gauge(53260, "Skerešovo", 48.500556, 20.203056),
    Gauge(54020, "Tisovec", 48.678464, 19.943658),
    Gauge(54060, "Klenovec", 48.593744, 19.889701),
    Gauge(54100, "Rimavské Brezovo", 48.539219, 19.959581),
    Gauge(54140, "Kokava nad Rimavicou", 48.565126, 19.844113),
    Gauge(54220, "Hajnáčka", 48.216858, 19.949122),
    Gauge(54300, "Hostice", 48.236667, 20.066667),
    Gauge(54320, "Teplý Vrch", 48.473106, 20.099111),
    Gauge(55120, "Malá Ida", 48.677805, 21.163679),
    Gauge(55160, "Buzica", 48.53, 21.074722),
    Gauge(55280, "Turňa nad Bodvou", 48.605556, 20.879167),
    Gauge(56040, "Vernár", 48.915833, 20.268333),
    Gauge(56100, "Hrabušice", 48.978383, 20.405589),
    Gauge(56135, "Uloža", 49.042292, 20.646765),
    Gauge(56160, "Rudňany", 48.880311, 20.669588),
    Gauge(57020, "Dobšinská Ľadová Jaskyňa", 48.87886, 20.299907),
    Gauge(57060, "Nálepkovo", 48.839444, 20.625),
    Gauge(57140, "Smolník", 48.72903, 20.729039),
    Gauge(57180, "Gelnica", 48.870808, 20.966556),
    Gauge(58020, "Košická Belá", 48.800954, 21.108177),
    Gauge(58060, "Klenov", 48.929562, 21.052938),
    Gauge(58100, "Lipovce", 49.047728, 20.9457),
    Gauge(59020, "Torysky", 49.093297, 20.681821),
    Gauge(59040, "Brezovica nad Torysou", 49.142222, 20.849722),
    Gauge(59160, "Prešov - Planetárium", 48.999849, 21.256577),
    Gauge(59180, "Osikov", 49.173056, 21.2625),
    Gauge(59220, "Kapušany", 49.048758, 21.332383),
    Gauge(59340, "Ploské", 48.817308, 21.324701),
    Gauge(60060, "Herľany", 48.799155, 21.474607),
    Gauge(60100, "Vyšný Čaj", 48.683333, 21.4025),
    Gauge(60160, "Milhosť", 48.540741, 21.269696),
)

GAUGES_BY_IND_ZRA: dict[int, Gauge] = {g.ind_zra: g for g in GAUGES}


def get_gauge(ind_zra: int) -> Gauge | None:
    """Return the gauge with the given ``ind_zra``, or ``None``."""
    return GAUGES_BY_IND_ZRA.get(ind_zra)


def nearest_gauge(latitude: float, longitude: float) -> Gauge:
    """Return the rain gauge closest to the given coordinates."""
    return min(GAUGES, key=lambda g: g.distance_km(latitude, longitude))
