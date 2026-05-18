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
    _IDX_LABEL_BG,
    _N_DBZ,
    _palette,
    encode_apng,
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
    # Palette = transparent + dBZ ramp + border + ring + dot + label bg.
    assert len(chunks[b"PLTE"]) == (1 + _N_DBZ + 4) * 3
    assert len(_palette()) == (1 + _N_DBZ + 4) * 3
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


def _ordered_chunks(png: bytes) -> list[tuple[bytes, bytes]]:
    """Every chunk in file order (APNG repeats ``fcTL``/``fdAT``)."""
    assert png[:8] == _PNG_SIG
    chunks: list[tuple[bytes, bytes]] = []
    pos = 8
    while pos < len(png):
        (length,) = struct.unpack_from(">I", png, pos)
        tag = png[pos + 4 : pos + 8]
        chunks.append((tag, png[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    return chunks


def test_encode_apng_assembles_a_valid_animation(fixture) -> None:
    frame = render_radar(fixture("radar_zmax.hdf"), _LAT, _LON)
    apng = encode_apng([frame, frame, frame])

    chunks = _ordered_chunks(apng)
    tags = [t for t, _ in chunks]
    # APNG control chunks precede the first frame; IEND closes the file.
    assert tags[:4] == [b"IHDR", b"PLTE", b"tRNS", b"acTL"]
    assert tags[-1] == b"IEND"

    payload = dict(chunks)
    num_frames, num_plays = struct.unpack(">II", payload[b"acTL"])
    assert num_frames == 3
    assert num_plays == 0  # 0 == loop forever

    assert tags.count(b"fcTL") == 3
    assert tags.count(b"IDAT") == 1  # frame 0 is a plain IDAT
    assert tags.count(b"fdAT") == 2  # frames 1.. are fdAT
    # The single shared sequence counter is contiguous from 0.
    seqs = [
        struct.unpack_from(">I", body)[0]
        for tag, body in chunks
        if tag in (b"fcTL", b"fdAT")
    ]
    assert seqs == [0, 1, 2, 3, 4]
    # Each frame spans the whole canvas (size matches IHDR).
    iw, ih = struct.unpack(">II", payload[b"IHDR"][:8])
    for tag, body in chunks:
        if tag == b"fcTL":
            _seq, w, h, x, y = struct.unpack_from(">IIIII", body)
            assert (w, h, x, y) == (iw, ih, 0, 0)


def test_encode_apng_single_frame_degrades_to_one_frame(fixture) -> None:
    frame = render_radar(fixture("radar_zmax.hdf"), _LAT, _LON)
    apng = encode_apng([frame])
    chunks = _ordered_chunks(apng)
    tags = [t for t, _ in chunks]
    assert dict(chunks)[b"acTL"][:4] == struct.pack(">I", 1)  # num_frames == 1
    assert tags.count(b"fcTL") == 1
    assert tags.count(b"fdAT") == 0
    assert tags.count(b"IDAT") == 1


def test_encode_apng_rejects_empty() -> None:
    with pytest.raises(ShmuDataError, match="zero frames"):
        encode_apng([])


def test_encode_apng_rejects_mismatched_frame_sizes(fixture) -> None:
    data = fixture("radar_zmax.hdf")
    small = render_radar(data, _LAT, _LON, radius_km=60.0)
    large = render_radar(data, _LAT, _LON, radius_km=150.0)
    assert (small.width, small.height) != (large.width, large.height)
    with pytest.raises(ShmuDataError, match="differ in size"):
        encode_apng([small, large])


def test_timestamp_label_is_stamped_and_distinguishes_frames(fixture) -> None:
    data = fixture("radar_zmax.hdf")
    plain = render_radar(data, _LAT, _LON)
    # Leading digit differs so the change is visible even on the trimmed
    # fixture crop (a long stamp's tail is clipped on such a tiny grid).
    a = render_radar(data, _LAT, _LON, label="2026-05-18 17:20")
    b = render_radar(data, _LAT, _LON, label="1026-05-18 17:20")

    # The stamp adds its opaque swatch; the unlabeled frame has none.
    assert _IDX_LABEL_BG in _indexed_pixels(a.png, _png_chunks(a.png))
    assert _IDX_LABEL_BG not in _indexed_pixels(plain.png, _png_chunks(plain.png))
    # A different timestamp -> different pixels, so a viewer can tell the
    # loop's frames apart while it plays.
    assert a.png != b.png
    assert (a.width, a.height) == (plain.width, plain.height)
