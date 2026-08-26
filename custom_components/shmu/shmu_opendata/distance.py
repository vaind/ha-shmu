"""Great-circle distance between geographic points.

Shared by the two station catalogues (:mod:`shmu_opendata.stations` and
:mod:`shmu_opendata.gauges`), which both answer "which entry is nearest this
location?".

Deliberately **not** part of :mod:`shmu_opendata.geo`: that module is specific
to the ODIM radar grid's Mercator projection and imports the HDF5 reader,
which a plain catalogue lookup must not drag in.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

#: IUGG mean Earth radius. Picking the closest of a set of stations tens of
#: kilometres apart needs km-scale accuracy at most, so a spherical model is
#: ample and avoids a geodesy dependency.
EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS84 points (degrees)."""
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))
