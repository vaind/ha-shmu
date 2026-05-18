"""Tests for the pure-Python radar renderer (crop + borders + dBZ PNG)."""

from __future__ import annotations

import struct
import zlib

import pytest

from custom_components.shmu.shmu_opendata.exceptions import ShmuDataError
from custom_components.shmu.shmu_opendata.geo import vicinity_box
from custom_components.shmu.shmu_opendata.odim import read_odim
from custom_components.shmu.shmu_opendata.radar import (
    _IDX_BORDER,
    _IDX_DOT,
    _N_DBZ,
    _palette,
    render_radar,
)

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
# Bratislava - Koliba (a real SHMÚ station, far SW Slovakia).
_LAT, _LON = 48.1686, 17.1106


def _png_chunks(png: bytes) -> dict[bytes, bytes]:
    assert png[:8] == _PNG_SIG
    chunks: dict[bytes, bytes] = {}
    pos = 8
    while pos < len(png):
        (length,) = struct.unpack_from(">I", png, pos)
        tag = png[pos + 4 : pos + 8]
        chunks[tag] = png[pos + 8 : pos + 8 + length]
        pos += 12 + length
    return chunks


def _indexed_pixels(png: bytes, chunks: dict[bytes, bytes]) -> set[int]:
    """Decode the palette PNG back to the set of palette indices used."""
    width, height = struct.unpack(">II", chunks[b"IHDR"][:8])
    raw = zlib.decompress(chunks[b"IDAT"])
    seen: set[int] = set()
    pos = 0
    for _ in range(height):
        assert raw[pos] == 0  # filter type None
        pos += 1
        seen.update(raw[pos : pos + width])
        pos += width
    return seen


def test_renders_valid_cropped_indexed_png(fixture) -> None:
    img = render_radar(fixture("radar_zmax.hdf"), _LAT, _LON)

    assert img.png[:8] == _PNG_SIG
    chunks = _png_chunks(img.png)
    width, height, depth, colour_type = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (width, height) == (img.width, img.height)
    assert depth == 8
    assert colour_type == 3  # palette
    assert chunks[b"tRNS"] == b"\x00"  # only index 0 is transparent
    assert b"IEND" in chunks
    # Palette = transparent + dBZ ramp + border + marker ring + marker dot.
    assert len(chunks[b"PLTE"]) == (1 + _N_DBZ + 3) * 3
    assert len(_palette()) == (1 + _N_DBZ + 3) * 3
    # Cropped to the station vicinity, so smaller than the 64x48 fixture grid.
    assert 0 < img.width < 64
    assert 0 < img.height < 48


def test_overlay_border_and_marker_are_drawn(fixture) -> None:
    img = render_radar(fixture("radar_zmax.hdf"), _LAT, _LON)
    used = _indexed_pixels(img.png, _png_chunks(img.png))
    assert _IDX_BORDER in used  # country borders rendered
    assert _IDX_DOT in used  # the station marker centre dot


def test_extent_is_the_crop_box_containing_the_station(fixture) -> None:
    img = render_radar(fixture("radar_zmax.hdf"), _LAT, _LON)
    assert img.south < img.north
    assert img.west < img.east
    # The crop is centred on the station, so it must contain it...
    assert img.south <= _LAT <= img.north
    assert img.west <= _LON <= img.east
    assert (img.center_lat, img.center_lon) == (_LAT, _LON)
    # ...and a strict sub-box of the full ODIM domain (~46-50.7 / 13.6-23.8).
    assert img.south > 46.04
    assert img.north < 50.7


def test_radius_controls_crop_size(fixture) -> None:
    data = fixture("radar_zmax.hdf")
    small = render_radar(data, _LAT, _LON, radius_km=60.0)
    large = render_radar(data, _LAT, _LON, radius_km=150.0)
    assert small.width <= large.width
    assert small.height <= large.height
    assert (small.north - small.south) < (large.north - large.south)


def test_reports_actual_strongest_echo_not_band_boundary(fixture) -> None:
    """max_dbz must be the decoded reflectivity of the peak rendered pixel,
    not the palette band's upper bound (PR #13 review). A huge radius makes
    the crop the whole grid, so the oracle is simple and deterministic."""
    raw_bytes = fixture("radar_zmax.hdf")
    o = read_odim(raw_bytes)
    img = render_radar(raw_bytes, _LAT, _LON, radius_km=1.0e6)
    assert img.product == "MAX"
    assert img.max_dbz is not None

    col0, row0, col1, row1 = vicinity_box(o, _LAT, _LON, 1.0e6)
    assert (col0, row0, col1, row1) == (0, 0, o.width, o.height)
    peak_raw = -1
    for b in o.raw:
        if b in (0, 255):
            continue
        if o.offset + o.gain * b >= 5.0 and b > peak_raw:
            peak_raw = b
    assert img.max_dbz == round(o.offset + o.gain * peak_raw, 1)
    assert img.max_dbz != float("inf")


def test_unsupported_product_raises_loudly(fixture) -> None:
    with pytest.raises(ShmuDataError, match="Unsupported radar product"):
        render_radar(fixture("radar_unsupported.hdf"), _LAT, _LON)


def test_non_hdf5_payload_raises() -> None:
    with pytest.raises(ShmuDataError):
        render_radar(b"not an hdf5 file at all", _LAT, _LON)
