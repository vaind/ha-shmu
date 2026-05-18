"""Render a SHMÚ ODIM reflectivity composite to a PNG radar image.

:mod:`shmu_opendata.odim` decodes the raw HDF5; this module knows what the
SHMÚ ``skcomp`` reflectivity composite *means* and turns it into a small,
map-overlayable PNG with a standard dBZ colour scale. The frame is cropped to
the **vicinity of the configured station** (the full mosaic spans ~Central
Europe, which is rarely what a user wants) and overlaid with **country
borders** and a **marker at the station** so the picture is self-locating.
Colour mapping, projection, border drawing and the PNG encoder are all pure
standard library (``zlib`` + ``math``), so the vendored library stays
HA-free, dependency-free and offline-testable — the same reason
:mod:`grib2` hand-rolls its decoder instead of pulling a binary wheel.

:func:`encode_apng` splices a buffer of recent frames into one animated PNG
(APNG — a backward-compatible PNG superset) so the same image entity can
show a **loop** of how the precipitation is moving. Each frame's compressed
pixel stream is cached on its :class:`RadarImage`, so building the loop is
just chunk concatenation — the costly per-pixel pass runs once per frame.

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
from collections.abc import Sequence
from dataclasses import dataclass

from .borders import BORDERS
from .exceptions import ShmuDataError
from .geo import lonlat_to_pixel, pixel_to_lonlat, vicinity_box
from .odim import OdimComposite, read_odim

#: ODIM quantity this renderer understands.
_DBZH = "DBZH"
#: Raw pixel sentinels in the SHMÚ DBZH composites (rest is gain/offset dBZ).
_RAW_NO_ECHO = 0
_RAW_NO_DATA = 255
#: Reflectivity below this (dBZ) is drawn transparent (speckle / clutter).
_MIN_DBZ = 5.0
#: Longest output edge after downsampling. The cropped window is already a
#: fraction of the 2270x1560 mosaic; this bounds the pure-Python per-pixel
#: pass. Stride sampling can thin a very small cell — an accepted trade-off
#: for an overview image refreshed every 5 minutes.
_MAX_EDGE = 760
#: Default crop: ~150 km around the station (≈300 km across) — local, but you
#: still see weather approaching from outside the immediate area.
_DEFAULT_RADIUS_KM = 150.0
#: Overlay colours (no pure grey/black/white in the dBZ ramp, so these stay
#: unambiguous over both echo and the transparent background).
_BORDER_RGB = (205, 205, 205)
_MARKER_RING_RGB = (10, 10, 10)
_MARKER_DOT_RGB = (255, 255, 255)
_MARKER_RADIUS_PX = 4
#: Playback time per loop frame, in milliseconds (the real frames are 5 min
#: apart; the loop is a fast replay so the motion is readable at a glance).
_FRAME_MS = 500

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

#: Palette layout: 0 = transparent, 1..N = dBZ bands, then the overlay colours.
_N_DBZ = len(_DBZ_RAMP)
_IDX_BORDER = _N_DBZ + 1
_IDX_RING = _N_DBZ + 2
_IDX_DOT = _N_DBZ + 3


@dataclass(frozen=True, slots=True)
class RadarImage:
    """A rendered radar frame plus the geographic box it covers.

    ``png`` is an 8-bit palette PNG (index 0 transparent) cropped to the
    station vicinity, with country borders and a station marker drawn on.
    ``south/west/north/east`` is that crop's WGS84 bounding box (ready for a
    Home Assistant map overlay); ``center_lat/center_lon`` is the station the
    crop is centred on. ``max_dbz`` is the strongest echo in the (downsampled)
    frame, or ``None`` when echo-free — handy as an "is it raining" signal.

    ``zstream`` is the zlib-compressed, PNG-filtered pixel stream backing
    ``png``. It is cached so :func:`encode_apng` can splice this frame into a
    radar **loop** without re-rendering or re-compressing it — the per-pixel
    pass already ran once when the frame was decoded.
    """

    png: bytes
    width: int
    height: int
    south: float
    west: float
    north: float
    east: float
    center_lat: float
    center_lon: float
    product: str
    max_dbz: float | None
    zstream: bytes


def _palette() -> bytes:
    plte = bytearray(b"\x00\x00\x00")  # index 0: transparent placeholder
    for _bound, (r, g, b) in _DBZ_RAMP:
        plte += bytes((r, g, b))
    plte += bytes(_BORDER_RGB)
    plte += bytes(_MARKER_RING_RGB)
    plte += bytes(_MARKER_DOT_RGB)
    return bytes(plte)


def _draw_line(
    rows: list[bytearray],
    w: int,
    h: int,
    p0: tuple[int, int],
    p1: tuple[int, int],
    idx: int,
) -> None:
    """Bresenham line, per-pixel clipped to the frame.

    Segments wholly off one side are skipped so projecting the full border
    set (most of it outside a vicinity crop) stays cheap.
    """
    x0, y0 = p0
    x1, y1 = p1
    if (x0 < 0 and x1 < 0) or (x0 >= w and x1 >= w):
        return
    if (y0 < 0 and y1 < 0) or (y0 >= h and y1 >= h):
        return
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        if 0 <= x0 < w and 0 <= y0 < h:
            rows[y0][x0] = idx
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _draw_marker(rows: list[bytearray], w: int, h: int, cx: int, cy: int) -> None:
    """A dark ring + white centre dot — a location pin readable on any
    background and not confusable with the weather colours."""
    r = _MARKER_RADIUS_PX
    inner, outer = (r - 0.8) ** 2, (r + 0.8) ** 2
    for yy in range(cy - r - 1, cy + r + 2):
        if not 0 <= yy < h:
            continue
        for xx in range(cx - r - 1, cx + r + 2):
            if 0 <= xx < w and inner <= (xx - cx) ** 2 + (yy - cy) ** 2 <= outer:
                rows[yy][xx] = _IDX_RING
    if 0 <= cx < w and 0 <= cy < h:
        rows[cy][cx] = _IDX_DOT


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


def _filtered_zstream(rows: list[bytearray]) -> bytes:
    """zlib-compress the scanlines (PNG filter type 0 / None per row).

    The result is reused verbatim as a still PNG ``IDAT`` *and* as an APNG
    frame body, so a buffered loop frame is never re-rendered or re-compressed.
    """
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter type 0 (None)
        raw += row
    return zlib.compress(bytes(raw), 6)


def _ihdr(width: int, height: int) -> bytes:
    return _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))


def _encode_png(width: int, height: int, zstream: bytes, palette: bytes) -> bytes:
    """Encode an 8-bit palette PNG (index 0 fully transparent)."""
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _ihdr(width, height),
            _png_chunk(b"PLTE", palette),
            _png_chunk(b"tRNS", b"\x00"),  # only index 0 is transparent
            _png_chunk(b"IDAT", zstream),
            _png_chunk(b"IEND", b""),
        )
    )


def encode_apng(images: Sequence[RadarImage], *, frame_ms: int = _FRAME_MS) -> bytes:
    """Splice buffered :class:`RadarImage` frames into one animated PNG.

    Frames must share the palette and dimensions — they always do here: the
    ODIM grid is fixed and the crop is centred on one constant station. Each
    frame's cached ``zstream`` is reused as-is, so assembling the loop every
    poll is pure chunk concatenation (no decode, no re-compression). A single
    image yields a valid one-frame APNG, i.e. it degrades to a still.

    APNG is a backward-compatible PNG superset (extra ``acTL``/``fcTL``/
    ``fdAT`` chunks), so the same ``image/png`` entity renders the animation
    with no frontend change. ``num_plays`` 0 means loop forever; every frame
    repaints the whole canvas (dispose ``NONE`` + blend ``SOURCE``).
    """
    if not images:
        raise ShmuDataError("Cannot build a radar loop from zero frames")
    width, height = images[0].width, images[0].height
    if any((im.width, im.height) != (width, height) for im in images):
        raise ShmuDataError("Radar loop frames differ in size")

    delay = struct.pack(">HH", frame_ms, 1000)  # delay_num / delay_den (s)
    parts = [
        b"\x89PNG\r\n\x1a\n",
        _ihdr(width, height),
        _png_chunk(b"PLTE", _palette()),
        _png_chunk(b"tRNS", b"\x00"),
        _png_chunk(b"acTL", struct.pack(">II", len(images), 0)),  # 0 = infinite
    ]
    seq = 0
    for i, im in enumerate(images):
        # fcTL: seq, w, h, x_off, y_off, delay_num, delay_den, dispose, blend.
        fctl = struct.pack(">IIIII", seq, width, height, 0, 0) + delay + b"\x00\x00"
        parts.append(_png_chunk(b"fcTL", fctl))
        seq += 1
        if i == 0:
            parts.append(_png_chunk(b"IDAT", im.zstream))
        else:
            parts.append(_png_chunk(b"fdAT", struct.pack(">I", seq) + im.zstream))
            seq += 1
    parts.append(_png_chunk(b"IEND", b""))
    return b"".join(parts)


def render_radar(
    data: bytes,
    latitude: float,
    longitude: float,
    *,
    radius_km: float = _DEFAULT_RADIUS_KM,
) -> RadarImage:
    """Decode a SHMÚ ODIM reflectivity composite, crop it to ``radius_km``
    around ``(latitude, longitude)``, overlay borders + a station marker and
    render it to a PNG.

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
    src_w = composite.width
    col0, row0, col1, row1 = vicinity_box(composite, latitude, longitude, radius_km)
    crop_w, crop_h = col1 - col0, row1 - row0
    step = max(1, (max(crop_w, crop_h) + _MAX_EDGE - 1) // _MAX_EDGE)
    out_w = (crop_w + step - 1) // step
    out_h = (crop_h + step - 1) // step

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
        sy = min(row0 + oy * step, composite.height - 1)
        base = sy * src_w
        row = bytearray(out_w)
        for ox in range(out_w):
            raw_val = src[base + min(col0 + ox * step, src_w - 1)]
            idx = lut[raw_val]
            row[ox] = idx
            if idx and raw_val > peak_raw:
                peak_raw = raw_val
        rows.append(row)

    # Borders & marker: project geo → full-grid px → cropped/downsampled px.
    def to_out(lon: float, lat: float) -> tuple[int, int]:
        col, r = lonlat_to_pixel(composite, lon, lat)
        return round((col - col0) / step), round((r - row0) / step)

    for line in BORDERS:
        prev = to_out(*line[0])
        for lon, lat in line[1:]:
            cur = to_out(lon, lat)
            _draw_line(rows, out_w, out_h, prev, cur, _IDX_BORDER)
            prev = cur
    mx, my = to_out(longitude, latitude)
    _draw_marker(rows, out_w, out_h, mx, my)

    zstream = _filtered_zstream(rows)
    png = _encode_png(out_w, out_h, zstream, _palette())
    max_dbz = None if peak_raw < 0 else round(offset + gain * peak_raw, 1)
    west, north = pixel_to_lonlat(composite, col0, row0)
    east, south = pixel_to_lonlat(composite, col1, row1)
    return RadarImage(
        png=png,
        width=out_w,
        height=out_h,
        south=south,
        west=west,
        north=north,
        east=east,
        center_lat=latitude,
        center_lon=longitude,
        product=composite.product,
        max_dbz=max_dbz,
        zstream=zstream,
    )
