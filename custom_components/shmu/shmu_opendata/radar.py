"""Render a SHMÚ ODIM reflectivity composite to a PNG radar image.

:mod:`shmu_opendata.odim` decodes the raw HDF5; this module knows what the
SHMÚ ``skcomp`` reflectivity composite *means* and turns it into a small,
map-overlayable PNG with a standard dBZ colour scale. Both the colour mapping
and the PNG encoder are pure standard library (``zlib`` only), so the vendored
library stays HA-free, dependency-free and offline-testable — the same reason
:mod:`grib2` hand-rolls its decoder instead of pulling a binary wheel.

Scope (verified live 2026-05-17, issue #6): the reflectivity products
``MAX`` (column-maximum, the default "is it raining / storms" picture) and
``CAPPI`` carry ODIM quantity ``DBZH`` as ``u8`` with a ``gain``/``offset``
scale and the two sentinel raw values ``0`` (no echo) and ``255`` (outside
radar coverage / no data). Any other quantity raises :class:`ShmuDataError`
rather than rendering a meaningless picture.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from .exceptions import ShmuDataError
from .odim import OdimComposite, read_odim

#: ODIM quantity this renderer understands.
_DBZH = "DBZH"
#: Raw pixel sentinels in the SHMÚ DBZH composites (rest is gain/offset dBZ).
_RAW_NO_ECHO = 0
_RAW_NO_DATA = 255
#: Reflectivity below this (dBZ) is drawn transparent (speckle / clutter).
_MIN_DBZ = 5.0
#: Longest output edge after downsampling (source is 2270x1560 ≈ 3.5 MP; a
#: pure-Python per-pixel pass over the full grid would be needlessly slow for
#: an at-a-glance overlay). Stride sampling can thin a very small cell — an
#: accepted trade-off for an overview image refreshed every 5 minutes.
_MAX_EDGE = 760

#: dBZ colour ramp: ``(upper_bound, (r, g, b))``, scanned low→high. A standard
#: weather-radar scale (cyan → green → yellow → red → magenta → white).
#: Palette index is the band position + 1; index 0 is reserved transparent.
_DBZ_RAMP: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (10.0, (100, 180, 230)),
    (15.0, (60, 130, 210)),
    (20.0, (40, 160, 90)),
    (25.0, (40, 200, 60)),
    (30.0, (130, 220, 50)),
    (35.0, (235, 235, 40)),
    (40.0, (245, 190, 35)),
    (45.0, (245, 130, 30)),
    (50.0, (235, 60, 30)),
    (55.0, (200, 30, 30)),
    (60.0, (225, 60, 180)),
    (65.0, (180, 80, 220)),
    (float("inf"), (245, 245, 245)),
)


@dataclass(frozen=True, slots=True)
class RadarImage:
    """A rendered radar frame plus the geographic box it covers.

    ``png`` is an 8-bit palette PNG (index 0 transparent). The extent is the
    ODIM corner bounding box in WGS84 degrees, ready for a Home Assistant map
    overlay. ``max_dbz`` is the strongest echo in the (downsampled) frame, or
    ``None`` when the frame is echo-free — handy as an "is it raining" signal.
    """

    png: bytes
    width: int
    height: int
    south: float
    west: float
    north: float
    east: float
    product: str
    max_dbz: float | None


def _palette() -> bytes:
    plte = bytearray(b"\x00\x00\x00")  # index 0: transparent placeholder
    for _bound, (r, g, b) in _DBZ_RAMP:
        plte += bytes((r, g, b))
    return bytes(plte)


def _dbz_to_index(dbz: float) -> int:
    """Palette index (1-based) for a reflectivity value at/above ``_MIN_DBZ``."""
    for band, (bound, _rgb) in enumerate(_DBZ_RAMP):
        if dbz < bound:
            return band + 1
    return len(_DBZ_RAMP)


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def _encode_indexed_png(
    width: int, height: int, rows: list[bytearray], palette: bytes
) -> bytes:
    """Encode an 8-bit palette PNG (index 0 fully transparent)."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter type 0 (None)
        raw += row
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"PLTE", palette),
            _png_chunk(b"tRNS", b"\x00"),  # only index 0 is transparent
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6)),
            _png_chunk(b"IEND", b""),
        )
    )


def render_radar(data: bytes) -> RadarImage:
    """Decode a SHMÚ ODIM reflectivity composite and render it to a PNG.

    Raises :class:`ShmuDataError` for a non-reflectivity product so an
    upstream change is loud rather than silently mis-coloured.
    """
    composite: OdimComposite = read_odim(data)
    if composite.quantity != _DBZH or composite.dtype != "u8":
        raise ShmuDataError(
            f"Unsupported radar product {composite.product!r} "
            f"(quantity {composite.quantity!r}); expected a {_DBZH} composite"
        )

    src = composite.raw
    src_w, src_h = composite.width, composite.height
    step = max(1, (max(src_w, src_h) + _MAX_EDGE - 1) // _MAX_EDGE)
    out_w = (src_w + step - 1) // step
    out_h = (src_h + step - 1) // step

    gain, offset = composite.gain, composite.offset
    # Precompute raw byte → palette index (256 entries; sentinels → 0).
    lut = bytearray(256)
    for raw_val in range(256):
        if raw_val in (_RAW_NO_ECHO, _RAW_NO_DATA):
            continue
        dbz = offset + gain * raw_val
        if dbz >= _MIN_DBZ:
            lut[raw_val] = _dbz_to_index(dbz)

    rows: list[bytearray] = []
    # Track the strongest *raw* byte that maps to a visible band so the
    # reported peak is the actual decoded reflectivity of the rendered
    # (downsampled) frame, not a palette-band boundary.
    peak_raw = -1
    for oy in range(out_h):
        base = (oy * step) * src_w
        row = bytearray(out_w)
        for ox in range(out_w):
            raw_val = src[base + ox * step]
            idx = lut[raw_val]
            row[ox] = idx
            if idx and raw_val > peak_raw:
                peak_raw = raw_val
        rows.append(row)

    png = _encode_indexed_png(out_w, out_h, rows, _palette())
    max_dbz = None if peak_raw < 0 else round(offset + gain * peak_raw, 1)
    return RadarImage(
        png=png,
        width=out_w,
        height=out_h,
        south=composite.ll_lat,
        west=composite.ll_lon,
        north=composite.ur_lat,
        east=composite.ur_lon,
        product=composite.product,
        max_dbz=max_dbz,
    )
