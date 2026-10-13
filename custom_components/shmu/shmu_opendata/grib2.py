"""Minimal pure-Python GRIB2 decoder for SHMÚ ALADIN forecast files.

This is **not** a general GRIB2 library. It decodes exactly what SHMÚ's
``aladin/sk/4.5km`` open-data files contain, verified against live data in the
Phase-2a spike (issue #2):

* edition 2, every field packed with **Data Representation Template 5.0
  ("simple packing")** — no JPEG2000/PNG/CCSDS, so no C codec is needed;
* a Section-6 **bitmap** masking the rectangular grid down to the Slovakia
  sub-domain (so ``Section 7`` holds only the unmasked values, in scan order).

Anything outside that scope (other packing templates, no-bitmap files) raises
:class:`ShmuDataError` *loudly* rather than silently returning wrong numbers —
if SHMÚ ever changes the encoding we want a clear failure, not corrupt
forecasts. The fixed grid geometry is intentionally **not** interpreted here;
it lives in :mod:`shmu_opendata.forecast` because it never changes.

There are two ways in, over one shared parse. :func:`iter_messages` parses and
validates every message but leaves its values packed, so a caller reading a
single grid point unpacks only that point (:meth:`Grib2Message.value_at`);
:func:`iter_fields` unpacks whole grids. All validation lives in the shared
parse, so a format change fails just as loudly whichever way a file is read.

Reference: WMO-No. 306 Vol. I.2, FM 92 GRIB Edition 2.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .exceptions import ShmuDataError

_MAGIC = b"GRIB"
_END = b"7777"
_SIMPLE_PACKING = 0
_IEEE_PACKING = 4
_SUPPORTED_TEMPLATES = frozenset({_SIMPLE_PACKING, _IEEE_PACKING})
#: GRIB marks an absent numeric field by setting every bit — see
#: :func:`_fixed_surface`.
_MISSING_U8 = 0xFF
_MISSING_U32 = 0xFFFFFFFF


def _u(data: bytes, offset: int, length: int) -> int:
    """Read a big-endian unsigned integer."""
    return int.from_bytes(data[offset : offset + length], "big")


def _grib_int(data: bytes, offset: int, length: int) -> int:
    """Read a GRIB sign-magnitude integer (the MSB is the sign bit).

    GRIB2 stores the binary/decimal scale factors this way, *not* as two's
    complement; decoding them as two's complement yields absurd exponents.
    """
    raw = int.from_bytes(data[offset : offset + length], "big")
    sign_bit = 1 << (8 * length - 1)
    if raw & sign_bit:
        return -(raw & (sign_bit - 1))
    return raw


def _fixed_surface(section4: bytes) -> float | None:
    """Value of the first fixed surface, in the units of its level type.

    Section 4 gives the level as a sign-magnitude scale factor (octet 24) and
    a scaled value (octets 25-28): ``value = scaled / 10**scale``. Either is
    all-ones when the encoder marks the level as absent, which is GRIB's own
    "missing" convention — reported as ``None`` rather than decoded, since a
    255 scale factor would otherwise read as an exponent of -127.
    """
    if section4[23] == _MISSING_U8 or _u(section4, 24, 4) == _MISSING_U32:
        return None
    return _u(section4, 24, 4) / 10.0 ** _grib_int(section4, 23, 1)


@dataclass(frozen=True, slots=True)
class Grib2Field:
    """One decoded GRIB2 message (a single 2-D field on the grid).

    ``values`` is in grid scan order, length ``nx * ny``; masked points are
    ``None``. ``param`` identifies the quantity as
    ``(discipline, parameter_category, parameter_number, level_type)`` —
    enough to pick e.g. 2 m temperature out of a multi-field file. Geometry is
    deliberately limited to ``nx``/``ny``/``scan_mode``; the projection is the
    caller's concern (the grid is fixed, see :mod:`forecast`).

    ``level`` is *where* that quantity sits — the first fixed surface's value
    in its own level type's units (Pa for isobaric level type 100, m for
    height-above-ground 103), or ``None`` if the message marks it missing.
    ``param`` alone cannot separate the five pressure levels ALADIN publishes
    the same quantity on, so a caller picking one addresses it as
    ``(*param, level)``.
    """

    reference_time: datetime
    param: tuple[int, int, int, int]
    level: float | None
    nx: int
    ny: int
    scan_mode: int
    values: tuple[float | None, ...]

    def value_at(self, i: int, j: int) -> float | None:
        """Value at column ``i`` (W→E) row ``j`` (S→N), or ``None`` if masked.

        Assumes scan mode ``0x40`` (the only one SHMÚ uses): +i first, +j
        northward, i consecutive — i.e. row-major from the first grid point.
        """
        return self.values[j * self.nx + i]


@dataclass(frozen=True, slots=True)
class Grib2Message:
    """One parsed, validated GRIB2 message whose values are still packed.

    Same identity and geometry as :class:`Grib2Field`, plus the raw sections
    needed to unpack it — either one grid point (:meth:`value_at`) or the
    whole grid (:meth:`decode`). The forecast reads a single location, so
    unpacking all ~2 500 values of every message only to keep one was nearly
    all of its cost.

    Deferring the unpack loses no loudness: :func:`iter_messages` has already
    checked the template, the bitmap and that Section 7 is long enough for
    every value, and past that point every bit pattern is a valid packed value.
    """

    reference_time: datetime
    param: tuple[int, int, int, int]
    level: float | None
    nx: int
    ny: int
    scan_mode: int
    data_template: int = field(repr=False)
    section5: bytes = field(repr=False)
    #: ``None`` when every grid point carries a value (indicator 255).
    bitmap: bytes | None = field(repr=False)
    section7: bytes = field(repr=False)

    def value_at(self, i: int, j: int) -> float | None:
        """Value at column ``i`` row ``j``, or ``None`` if masked.

        Indexed exactly like :meth:`Grib2Field.value_at` and bit-identical to
        it, but unpacks only this one point.
        """
        if not (0 <= i < self.nx and 0 <= j < self.ny):
            raise IndexError(f"Grid point ({i}, {j}) is outside {self.nx}x{self.ny}")
        k = j * self.nx + i
        index = k
        bitmap = self.bitmap
        if bitmap is not None:
            byte, bit = k >> 3, k & 7
            if not (bitmap[byte] >> (7 - bit)) & 1:
                return None
            # Section 7 holds only the unmasked points, in scan order, so a
            # point's slot there is the number of set bitmap bits before it.
            index = (
                int.from_bytes(bitmap[:byte]).bit_count()
                + (bitmap[byte] >> (8 - bit)).bit_count()
            )
        if self.data_template == _SIMPLE_PACKING:
            return _simple_packing_at(self.section5, self.section7, index)
        return _ieee_at(self.section5, self.section7, index)

    def decode(self) -> Grib2Field:
        """Unpack every grid point into a :class:`Grib2Field`."""
        npts = self.nx * self.ny
        bitmap = self.bitmap
        present = (
            None
            if bitmap is None
            else [bool((bitmap[k >> 3] >> (7 - (k & 7))) & 1) for k in range(npts)]
        )
        n_values = npts if present is None else sum(present)
        if self.data_template == _SIMPLE_PACKING:
            unpacked = _decode_simple_packing(self.section5, self.section7, n_values)
        else:  # _IEEE_PACKING — the only other member of _SUPPORTED_TEMPLATES
            unpacked = _decode_ieee(self.section5, self.section7, n_values)
        return Grib2Field(
            reference_time=self.reference_time,
            param=self.param,
            level=self.level,
            nx=self.nx,
            ny=self.ny,
            scan_mode=self.scan_mode,
            values=_scatter(unpacked, present),
        )


def _scatter(
    unpacked: list[float], bitmap: list[bool] | None
) -> tuple[float | None, ...]:
    """Place the (scan-order) decoded values back onto the full grid.

    Section 7 holds values only for unmasked points when a bitmap is present;
    masked grid positions become ``None``.
    """
    if bitmap is None:
        return tuple(unpacked)
    it = iter(unpacked)
    return tuple(next(it) if present else None for present in bitmap)


def _simple_packing_params(section5: bytes) -> tuple[float, float, int]:
    """``(base, scale, nbits)`` of DRT 5.0, so that ``value = base + X·scale``.

    Unpacks ``value = (R + X·2**E) / 10**D`` with the division folded into two
    constants. Shared by the whole-grid and the single-point unpack so the two
    perform the same float operations and cannot round differently.
    """
    reference = struct.unpack(">f", section5[11:15])[0]
    binary_scale = _grib_int(section5, 15, 2)
    decimal_scale = _grib_int(section5, 17, 2)
    factor = 10.0**-decimal_scale
    return reference * factor, (2.0**binary_scale) * factor, section5[19]


def _decode_simple_packing(
    section5: bytes, section7: bytes, n_values: int
) -> list[float]:
    """Unpack every DRT 5.0 value.

    ``X`` is an ``nbits``-wide unsigned integer from the big-endian bit stream.
    """
    base, scale, nbits = _simple_packing_params(section5)

    if nbits == 0:
        # Constant field: every (unmasked) point equals the reference value.
        return [base] * n_values

    unpacked: list[float] = []
    mask = (1 << nbits) - 1
    bit_buffer = 0
    bits_in_buffer = 0
    byte_iter = iter(section7[5:])
    for _ in range(n_values):
        while bits_in_buffer < nbits:
            bit_buffer = (bit_buffer << 8) | next(byte_iter)
            bits_in_buffer += 8
        x = (bit_buffer >> (bits_in_buffer - nbits)) & mask
        bits_in_buffer -= nbits
        unpacked.append(base + x * scale)
    return unpacked


def _simple_packing_at(section5: bytes, section7: bytes, index: int) -> float:
    """Unpack only the ``index``-th DRT 5.0 value.

    Simple packing has no per-value framing — every value is exactly ``nbits``
    wide — so value ``index`` starts at bit ``index·nbits`` of the payload.
    Reading just the bytes that span it as one big-endian integer and shifting
    the value out is O(1), where walking the stream to it is O(index).
    """
    base, scale, nbits = _simple_packing_params(section5)
    if nbits == 0:
        return base
    start = index * nbits
    first = start >> 3
    end = (start + nbits + 7) >> 3
    span = int.from_bytes(section7[5 + first : 5 + end])
    x = (span >> (8 * end - start - nbits)) & ((1 << nbits) - 1)
    return base + x * scale


def _ieee_format(section5: bytes) -> tuple[str, int]:
    """``struct`` format and byte width of a DRT 5.4 value.

    Precision octet: 1 = 32-bit, 2 = 64-bit; 3 (128-bit) has no ``struct``
    format and SHMÚ does not use it, so it raises rather than mis-reading.
    """
    precision = section5[11]
    if precision == 1:
        return ">f", 4
    if precision == 2:
        return ">d", 8
    raise ShmuDataError(f"Unsupported IEEE float precision {precision} in DRT 5.4")


def _decode_ieee(section5: bytes, section7: bytes, n_values: int) -> list[float]:
    """Unpack every DRT 5.4 value: raw big-endian IEEE 754 floats.

    SHMÚ uses this only for a constant orography field, but decoding it keeps
    the "fail loud only on a *truly* unsupported template" contract intact (no
    field is silently dropped).
    """
    fmt, width = _ieee_format(section5)
    payload = section7[5:]
    return [struct.unpack_from(fmt, payload, k * width)[0] for k in range(n_values)]


def _ieee_at(section5: bytes, section7: bytes, index: int) -> float:
    """Unpack only the ``index``-th DRT 5.4 value (fixed width, so O(1))."""
    fmt, width = _ieee_format(section5)
    return float(struct.unpack_from(fmt, section7, 5 + index * width)[0])


def _payload_bytes_needed(template: int, section5: bytes, n_values: int) -> int:
    """Section 7 payload length (after its 5-byte header) ``n_values`` need."""
    if template == _SIMPLE_PACKING:
        return (n_values * section5[19] + 7) // 8
    return n_values * _ieee_format(section5)[1]


def iter_messages(data: bytes) -> Iterator[Grib2Message]:
    """Yield every message in a GRIB2 file (each ``GRIB…7777``), still packed.

    Every message is fully validated here, whether or not anyone unpacks it.
    Raises :class:`ShmuDataError` on a non-edition-2 message, an unsupported
    packing template, or a structurally invalid message — never silently
    skipped, so an upstream format change surfaces immediately.
    """
    pos = 0
    size = len(data)
    while pos < size:
        if data[pos : pos + 4] != _MAGIC:
            # Trailing whitespace/newline after the last 7777 is harmless.
            if data[pos:].strip(b"\r\n ") == b"":
                return
            raise ShmuDataError(f"Expected 'GRIB' at offset {pos}")
        edition = data[pos + 7]
        if edition != 2:
            raise ShmuDataError(f"Unsupported GRIB edition {edition} (need 2)")
        discipline = data[pos + 6]
        total_len = _u(data, pos + 8, 8)
        end = pos + total_len
        if total_len < 16 or end > size:
            raise ShmuDataError("Truncated GRIB2 message")

        reference_time: datetime | None = None
        param: tuple[int, int, int, int] | None = None
        level: float | None = None
        npts = nx = ny = scan_mode = 0
        data_template = -1
        bitmap: bytes | None = None
        section5: bytes | None = None
        section7: bytes | None = None

        p = pos + 16
        while p < end:
            if data[p : p + 4] == _END:
                break
            sec_len = _u(data, p, 4)
            sec_num = data[p + 4]
            if sec_len == 0 or p + sec_len > end:
                raise ShmuDataError(f"Bad section length in section {sec_num}")
            sec = data[p : p + sec_len]
            if sec_num == 1:
                reference_time = datetime(
                    _u(sec, 12, 2),
                    sec[14],
                    sec[15],
                    sec[16],
                    sec[17],
                    sec[18],
                    tzinfo=UTC,
                )
            elif sec_num == 3:
                npts = _u(sec, 6, 4)
                # Lambert template (3.30 layout); SHMÚ writes the template
                # number as 33 but the field layout is the standard one.
                nx = _u(sec, 30, 4)
                ny = _u(sec, 34, 4)
                scan_mode = sec[64]
            elif sec_num == 4:
                # Octets 10/11 (category/number) and 23-28 (the first fixed
                # surface) sit at the same offsets in templates 4.0 and 4.8,
                # the only two SHMÚ uses, so one path reads both.
                param = (discipline, sec[9], sec[10], sec[22])
                level = _fixed_surface(sec)
            elif sec_num == 5:
                data_template = _u(sec, 9, 2)
                if data_template not in _SUPPORTED_TEMPLATES:
                    raise ShmuDataError(
                        f"Unsupported data representation template "
                        f"5.{data_template} (only 5.0 simple packing and "
                        "5.4 IEEE float are implemented)"
                    )
                section5 = sec
            elif sec_num == 6:
                indicator = sec[5]
                if indicator == 0:
                    bitmap = sec[6:]
                elif indicator == 255:
                    bitmap = None
                else:
                    # 254 = "reuse a previously defined bitmap"; SHMÚ files put
                    # one bitmap per message, so this is unexpected here.
                    raise ShmuDataError(f"Unsupported bitmap indicator {indicator}")
            elif sec_num == 7:
                section7 = sec
            p += sec_len

        if (
            reference_time is None
            or param is None
            or section5 is None
            or section7 is None
            or nx * ny != npts
        ):
            raise ShmuDataError("Incomplete GRIB2 message (missing a section)")

        n_values = npts
        if bitmap is not None:
            bitmap_bytes = (npts + 7) // 8
            if len(bitmap) < bitmap_bytes:
                raise ShmuDataError(
                    f"Bitmap covers {len(bitmap) * 8} points, grid has {npts}"
                )
            # The bitmap is padded to a whole octet; only its first npts bits
            # are grid points.
            n_values = (
                int.from_bytes(bitmap[:bitmap_bytes]) >> (8 * bitmap_bytes - npts)
            ).bit_count()
        needed = _payload_bytes_needed(data_template, section5, n_values)
        if len(section7) - 5 < needed:
            raise ShmuDataError(
                f"Section 7 holds {len(section7) - 5} bytes; {n_values} values "
                f"need {needed}"
            )

        yield Grib2Message(
            reference_time=reference_time,
            param=param,
            level=level,
            nx=nx,
            ny=ny,
            scan_mode=scan_mode,
            data_template=data_template,
            section5=section5,
            bitmap=bitmap,
            section7=section7,
        )
        pos = end


def iter_fields(data: bytes) -> Iterator[Grib2Field]:
    """Yield every message of a GRIB2 file with its whole grid unpacked.

    Raises exactly as :func:`iter_messages` does. A caller that reads only a
    few grid points should use that instead and unpack per point.
    """
    for message in iter_messages(data):
        yield message.decode()
