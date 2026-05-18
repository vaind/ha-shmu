"""Tests for the ODIM Mercator projection / vicinity-crop helpers."""

from __future__ import annotations

from custom_components.shmu.shmu_opendata.geo import (
    lonlat_to_pixel,
    pixel_to_lonlat,
    vicinity_box,
)
from custom_components.shmu.shmu_opendata.odim import read_odim


def _composite(fixture):
    return read_odim(fixture("radar_zmax.hdf"))


def test_corners_project_to_grid_extent(fixture) -> None:
    """Calibration is from the ODIM corners, so they must map exactly."""
    o = _composite(fixture)
    nw = lonlat_to_pixel(o, o.ll_lon, o.ur_lat)  # west / north
    se = lonlat_to_pixel(o, o.ur_lon, o.ll_lat)  # east / south
    assert nw == (0.0, 0.0)
    assert se[0] == float(o.width)
    assert se[1] == float(o.height)


def test_projection_round_trips(fixture) -> None:
    o = _composite(fixture)
    for lat, lon in ((48.1686, 17.1106), (47.8733, 18.1944), (49.0, 21.2)):
        col, row = lonlat_to_pixel(o, lon, lat)
        back_lon, back_lat = pixel_to_lonlat(o, col, row)
        assert abs(back_lon - lon) < 1e-6
        assert abs(back_lat - lat) < 1e-6


def test_north_is_row_zero(fixture) -> None:
    o = _composite(fixture)
    _, row_north = lonlat_to_pixel(o, 19.0, o.ur_lat)
    _, row_south = lonlat_to_pixel(o, 19.0, o.ll_lat)
    assert row_north < row_south  # ODIM row 0 = north edge


def test_vicinity_box_is_clamped_and_centred(fixture) -> None:
    o = _composite(fixture)
    col0, row0, col1, row1 = vicinity_box(o, 47.8733, 18.1944, 150.0)
    assert 0 <= col0 < col1 <= o.width
    assert 0 <= row0 < row1 <= o.height
    # Strictly inside the full grid for a station well within the domain.
    assert (col0, row0) != (0, 0) or (col1, row1) != (o.width, o.height)
    # The station's own pixel lies inside the returned window.
    sc, sr = lonlat_to_pixel(o, 18.1944, 47.8733)
    assert col0 <= sc <= col1
    assert row0 <= sr <= row1


def test_oversized_radius_degrades_to_full_grid(fixture) -> None:
    """A huge radius must clamp (Mercator domain) to the whole grid, not raise."""
    o = _composite(fixture)
    assert vicinity_box(o, 47.8733, 18.1944, 1.0e6) == (0, 0, o.width, o.height)
