"""Tests for the pure-Python radar renderer (PNG + dBZ palette)."""

from __future__ import annotations

import struct

import pytest

from custom_components.shmu.shmu_opendata.exceptions import ShmuDataError
from custom_components.shmu.shmu_opendata.radar import render_radar

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


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


def test_renders_valid_indexed_png(fixture) -> None:
    img = render_radar(fixture("radar_zmax.hdf"))

    assert img.png[:8] == _PNG_SIG
    chunks = _png_chunks(img.png)
    width, height, depth, colour_type = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (width, height) == (img.width, img.height)
    assert depth == 8
    assert colour_type == 3  # palette
    assert len(chunks[b"PLTE"]) % 3 == 0
    assert chunks[b"tRNS"] == b"\x00"  # palette index 0 transparent
    assert b"IEND" in chunks
    # Fixture grid (64x48) is below the downsample threshold -> kept 1:1.
    assert (img.width, img.height) == (64, 48)


def test_extent_is_the_odim_corner_box(fixture) -> None:
    img = render_radar(fixture("radar_zmax.hdf"))
    assert 45.0 < img.south < 47.0
    assert 13.0 < img.west < 14.0
    assert 50.0 < img.north < 51.0
    assert 23.0 < img.east < 24.0
    assert img.south < img.north
    assert img.west < img.east


def test_reports_strongest_echo(fixture) -> None:
    img = render_radar(fixture("radar_zmax.hdf"))
    # The fixture ramps raw bytes across the whole DBZH scale, so a strong
    # echo is present and reported in dBZ.
    assert img.max_dbz is not None
    assert 5.0 <= img.max_dbz <= 70.0
    assert img.product == "MAX"


def test_unsupported_product_raises_loudly(fixture) -> None:
    with pytest.raises(ShmuDataError, match="Unsupported radar product"):
        render_radar(fixture("radar_unsupported.hdf"))


def test_non_hdf5_payload_raises() -> None:
    with pytest.raises(ShmuDataError):
        render_radar(b"not an hdf5 file at all")
