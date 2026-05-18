"""Geographic mapping for the SHMÚ ODIM radar grid.

The composite is a regular grid in a spherical Mercator projection
(``+proj=merc`` with a secant latitude). In Mercator the pixel column is
**linear in longitude** and the pixel row is **linear in the Mercator
ordinate** ``ln(tan(π/4 + φ/2))``. That lets us calibrate the whole
lon/lat → pixel mapping from just the ODIM ``/where`` corner coordinates the
reader already exposes — the projection's radius, central meridian and
secant-parallel only contribute a scale/offset, which the corner calibration
absorbs. So this needs no projection-library and stays pure ``math``.

Used to (a) crop the ~Central-Europe mosaic to the vicinity of the configured
station and (b) place country borders and the station marker (see
:mod:`shmu_opendata.radar`).
"""

from __future__ import annotations

import math

from .odim import OdimComposite

#: Rough degrees-of-latitude per kilometre (mean Earth radius). Good to well
#: under a pixel at radar resolution — the crop only needs ~km accuracy.
_DEG_LAT_PER_KM = 1.0 / 111.195


def mercator_y(lat_deg: float) -> float:
    """Mercator ordinate for a latitude (radius/scale cancel in calibration)."""
    return math.log(math.tan(math.pi / 4.0 + math.radians(lat_deg) / 2.0))


def lonlat_to_pixel(
    composite: OdimComposite, lon: float, lat: float
) -> tuple[float, float]:
    """Fractional ``(col, row)`` of a lon/lat in the full composite grid.

    Row 0 is the north edge (ODIM convention). The result may fall outside
    ``[0, width] x [0, height]`` for points beyond the mosaic.
    """
    west, east = composite.ll_lon, composite.ur_lon
    north, south = composite.ur_lat, composite.ll_lat
    col = (lon - west) / (east - west) * composite.width
    y_north, y_south = mercator_y(north), mercator_y(south)
    row = (y_north - mercator_y(lat)) / (y_north - y_south) * composite.height
    return col, row


def pixel_to_lonlat(
    composite: OdimComposite, col: float, row: float
) -> tuple[float, float]:
    """Inverse of :func:`lonlat_to_pixel` — used for the cropped frame's box."""
    west, east = composite.ll_lon, composite.ur_lon
    north, south = composite.ur_lat, composite.ll_lat
    lon = west + col / composite.width * (east - west)
    y_north, y_south = mercator_y(north), mercator_y(south)
    y = y_north - row / composite.height * (y_north - y_south)
    lat = math.degrees(2.0 * math.atan(math.exp(y)) - math.pi / 2.0)
    return lon, lat


def vicinity_box(
    composite: OdimComposite, lat: float, lon: float, radius_km: float
) -> tuple[int, int, int, int]:
    """Pixel crop window ``(col0, row0, col1, row1)`` ≈ ``radius_km`` around a
    point, clamped to the grid (half-open: ``col0 <= c < col1``).

    The geographic ``±radius`` box is projected and its pixel bounding box is
    taken, so Mercator's mild latitudinal stretch is handled correctly.
    """
    d_lat = radius_km * _DEG_LAT_PER_KM
    d_lon = d_lat / max(math.cos(math.radians(lat)), 1e-6)
    # Clamp to the Mercator-valid range so an over-large radius degrades to
    # "the whole grid" instead of blowing up mercator_y().
    north = min(lat + d_lat, 85.0)
    south = max(lat - d_lat, -85.0)
    corners = (
        lonlat_to_pixel(composite, lon - d_lon, north),  # NW
        lonlat_to_pixel(composite, lon + d_lon, south),  # SE
    )
    cols = [c for c, _ in corners]
    rows = [r for _, r in corners]
    col0 = max(0, min(composite.width - 1, math.floor(min(cols))))
    col1 = max(col0 + 1, min(composite.width, math.ceil(max(cols))))
    row0 = max(0, min(composite.height - 1, math.floor(min(rows))))
    row1 = max(row0 + 1, min(composite.height, math.ceil(max(rows))))
    return col0, row0, col1, row1
