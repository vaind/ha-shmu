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

#: Background swatch behind the baked-in timestamp so it stays legible over
#: both echo and the (transparent) no-echo background.
_LABEL_BG_RGB = (15, 15, 15)

#: Palette layout: 0 = transparent, 1..N = dBZ bands, then the overlay colours.
_N_DBZ = len(_DBZ_RAMP)
_IDX_BORDER = _N_DBZ + 1
_IDX_RING = _N_DBZ + 2
_IDX_DOT = _N_DBZ + 3
_IDX_LABEL_BG = _N_DBZ + 4

#: 3x5 bitmap font, just the glyphs a localized ``valid_at`` needs
#: (``YYYY-MM-DD HH:MM``). Each row is 3 bits, MSB = leftmost pixel; a
#: hand-rolled font keeps the renderer pure-stdlib (no Pillow), the same
#: no-binary-deps reason borders/markers are hand-drawn.
_FONT_3X5: dict[str, tuple[int, int, int, int, int]] = {
    "0": (0b111, 0b101, 0b101, 0b101, 0b111),
    "1": (0b010, 0b110, 0b010, 0b010, 0b111),
    "2": (0b111, 0b001, 0b111, 0b100, 0b111),
    "3": (0b111, 0b001, 0b111, 0b001, 0b111),
    "4": (0b101, 0b101, 0b111, 0b001, 0b001),
    "5": (0b111, 0b100, 0b111, 0b001, 0b111),
    "6": (0b111, 0b100, 0b111, 0b101, 0b111),
    "7": (0b111, 0b001, 0b010, 0b010, 0b010),
    "8": (0b111, 0b101, 0b111, 0b101, 0b111),
    "9": (0b111, 0b101, 0b111, 0b001, 0b111),
    ":": (0b000, 0b010, 0b000, 0b010, 0b000),
    "-": (0b000, 0b000, 0b111, 0b000, 0b000),
    " ": (0b000, 0b000, 0b000, 0b000, 0b000),
}
_GLYPH_W = 3
_GLYPH_H = 5
#: Pixels between glyphs and around the label box, before scaling.
_LABEL_MARGIN = 4
_LABEL_PAD = 2

#: Loop progress: a row of small squares under the timestamp, one per frame,
#: solid up to the current frame and hollow after — so while the APNG rolls
#: forever you can see where "now" sits in the shown hour and when it resets.
#: Sitting on the same dark label swatch (white markers) keeps it readable
#: over any background, unlike a bottom bar that vanished on dark map areas.
#: Both colours reuse existing palette entries (no palette growth).


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
    plte += bytes(_LABEL_BG_RGB)
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


def _label_scale(width: int) -> int:
    """Integer glyph scale so the stamp stays readable but small.

    ~1 px per 220 px of crop width: 1 on the trimmed test grid, 2 on a real
    ~450 px vicinity crop."""
    return max(1, width // 220)


def _draw_label(rows: list[bytearray], w: int, h: int, text: str) -> None:
    """Stamp ``text`` (a pre-localized timestamp) top-left on a dark swatch.

    The string is already formatted by the caller — this only knows how to
    paint glyphs, so the renderer stays HA-free. Pixels outside the frame are
    clipped, so an over-narrow crop degrades gracefully instead of raising.
    """
    scale = _label_scale(w)
    glyph_w, glyph_h = _GLYPH_W * scale, _GLYPH_H * scale
    advance = glyph_w + scale  # one blank column between glyphs
    text_w = len(text) * advance - scale if text else 0
    pad = _LABEL_PAD * scale
    x0 = y0 = _LABEL_MARGIN * scale

    # Opaque swatch behind the text for guaranteed contrast.
    for yy in range(y0, min(y0 + glyph_h + 2 * pad, h)):
        row = rows[yy]
        for xx in range(x0, min(x0 + text_w + 2 * pad, w)):
            row[xx] = _IDX_LABEL_BG

    tx, ty = x0 + pad, y0 + pad
    for ci, ch in enumerate(text):
        glyph = _FONT_3X5.get(ch)
        if glyph is None:
            continue
        gx = tx + ci * advance
        for ry, bits in enumerate(glyph):
            for rx in range(_GLYPH_W):
                if not bits & (1 << (_GLYPH_W - 1 - rx)):
                    continue
                for sy in range(scale):
                    py = ty + ry * scale + sy
                    if not 0 <= py < h:
                        continue
                    prow = rows[py]
                    for sx in range(scale):
                        px = gx + rx * scale + sx
                        if 0 <= px < w:
                            prow[px] = _IDX_DOT


def _fill_rect(
    rows: list[bytearray], w: int, h: int, x: int, y: int, bw: int, bh: int, idx: int
) -> None:
    """Fill a ``bw`` by ``bh`` rectangle at ``(x, y)``, clipped to the frame."""
    for yy in range(max(0, y), min(y + bh, h)):
        row = rows[yy]
        for xx in range(max(0, x), min(x + bw, w)):
            row[xx] = idx


def _draw_progress(
    rows: list[bytearray], w: int, h: int, index: int, total: int
) -> None:
    """Stamp the per-frame step markers just below the timestamp swatch.

    ``total`` squares on a dark swatch: solid (white) up to ``index``, hollow
    (white outline) after — so the forever-rolling loop shows where "now" is
    and snaps back on wrap. White-on-dark stays visible over any background.
    Geometry mirrors :func:`_draw_label` so it sits directly under the time;
    everything is clipped, so a tiny crop degrades gracefully.
    """
    scale = _label_scale(w)
    pad = _LABEL_PAD * scale
    margin = _LABEL_MARGIN * scale
    sq = _GLYPH_W * scale  # match the digit width for a tidy stack
    gap = scale
    # Directly under the timestamp box (label height + a one-unit gap).
    box_y = margin + _GLYPH_H * scale + 2 * pad + scale
    markers_w = total * (sq + gap) - gap
    _fill_rect(
        rows, w, h, margin, box_y, markers_w + 2 * pad, sq + 2 * pad, _IDX_LABEL_BG
    )

    mx, my = margin + pad, box_y + pad
    for k in range(total):
        x = mx + k * (sq + gap)
        if k <= index:
            _fill_rect(rows, w, h, x, my, sq, sq, _IDX_DOT)  # reached: solid
        elif sq >= 2:
            _fill_rect(rows, w, h, x, my, sq, sq, _IDX_DOT)  # outline...
            _fill_rect(rows, w, h, x + 1, my + 1, sq - 2, sq - 2, _IDX_LABEL_BG)
        else:
            _fill_rect(rows, w, h, x, my, sq, sq, _IDX_DOT)


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


def _rows_from_zstream(zstream: bytes, width: int, height: int) -> list[bytearray]:
    """Inverse of :func:`_filtered_zstream` — back to per-row palette indices.

    Lets the loop stamp a per-frame overlay (the progress bar) without
    keeping every frame's rows resident: the cheap cached ``zstream`` is the
    single source of truth, expanded transiently only while the loop is
    assembled.
    """
    raw = zlib.decompress(zstream)
    stride = width + 1  # one filter byte per scanline
    return [bytearray(raw[r * stride + 1 : r * stride + stride]) for r in range(height)]


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
    ODIM grid is fixed and the crop is centred on one constant station. A
    single image yields a valid one-frame APNG, i.e. it degrades to a still.

    Each frame gets a row of step markers under the timestamp marking its
    place in the sequence, so the forever-rolling loop is readable (you can
    see "now" advance and reset). It is loop-only: the cached ``zstream``
    (used by the still and the scrubbed-frame image) is expanded, stamped and
    recompressed here transiently — the costly ODIM decode/crop still runs
    once per frame, this only adds a cheap zlib round-trip per frame at
    assembly time.

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
    total = len(images)
    for i, im in enumerate(images):
        rows = _rows_from_zstream(im.zstream, width, height)
        _draw_progress(rows, width, height, i, total)
        zstream = _filtered_zstream(rows)
        # fcTL: seq, w, h, x_off, y_off, delay_num, delay_den, dispose, blend.
        fctl = struct.pack(">IIIII", seq, width, height, 0, 0) + delay + b"\x00\x00"
        parts.append(_png_chunk(b"fcTL", fctl))
        seq += 1
        if i == 0:
            parts.append(_png_chunk(b"IDAT", zstream))
        else:
            parts.append(_png_chunk(b"fdAT", struct.pack(">I", seq) + zstream))
            seq += 1
    parts.append(_png_chunk(b"IEND", b""))
    return b"".join(parts)


def render_radar(
    data: bytes,
    latitude: float,
    longitude: float,
    *,
    radius_km: float = _DEFAULT_RADIUS_KM,
    label: str | None = None,
) -> RadarImage:
    """Decode a SHMÚ ODIM reflectivity composite, crop it to ``radius_km``
    around ``(latitude, longitude)``, overlay borders + a station marker and
    render it to a PNG.

    ``label``, when given, is stamped top-left as an opaque timestamp so the
    frames are tellable apart while the loop plays. It is drawn verbatim:
    timezone conversion / formatting is the caller's job, keeping this
    renderer free of any Home Assistant (locale/tz) coupling.

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
    if label:
        _draw_label(rows, out_w, out_h, label)

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
