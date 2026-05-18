"""Tests for the pure-Python radar renderer (PNG + dBZ palette)."""

from __future__ import annotations

import struct

import pytest

from custom_components.shmu.shmu_opendata.exceptions import ShmuDataError
from custom_components.shmu.shmu_opendata.odim import read_odim
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


def test_reports_actual_strongest_echo_not_band_boundary(fixture) -> None:
    """max_dbz must be the decoded reflectivity of the peak rendered pixel,
    not the palette band's upper bound (PR #13 review)."""
    raw_bytes = fixture("radar_zmax.hdf")
    o = read_odim(raw_bytes)
    img = render_radar(raw_bytes)
    assert img.product == "MAX"
    assert img.max_dbz is not None

    # Recompute the expected peak: strongest non-sentinel byte in the
    # rendered (stride-sampled) grid that clears the visibility threshold.
    step = max(1, (max(o.width, o.height) + 760 - 1) // 760)
    peak_raw = -1
    for y in range(0, o.height, step):
        for x in range(0, o.width, step):
            b = o.raw[y * o.width + x]
            if b in (0, 255):
                continue
            if o.offset + o.gain * b >= 5.0 and b > peak_raw:
                peak_raw = b
    expected = round(o.offset + o.gain * peak_raw, 1)
    assert img.max_dbz == expected
    # Sanity: it is a genuine decoded value, not a band edge constant.
    assert img.max_dbz != float("inf")


def test_unsupported_product_raises_loudly(fixture) -> None:
    with pytest.raises(ShmuDataError, match="Unsupported radar product"):
        render_radar(fixture("radar_unsupported.hdf"))


def test_non_hdf5_payload_raises() -> None:
    with pytest.raises(ShmuDataError):
        render_radar(b"not an hdf5 file at all")
