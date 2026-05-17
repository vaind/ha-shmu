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

Reference: WMO-No. 306 Vol. I.2, FM 92 GRIB Edition 2.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from .exceptions import ShmuDataError

_MAGIC = b"GRIB"
_END = b"7777"
_SIMPLE_PACKING = 0
_IEEE_PACKING = 4
_SUPPORTED_TEMPLATES = frozenset({_SIMPLE_PACKING, _IEEE_PACKING})


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


@dataclass(frozen=True, slots=True)
class Grib2Field:
    """One decoded GRIB2 message (a single 2-D field on the grid).

    ``values`` is in grid scan order, length ``nx * ny``; masked points are
    ``None``. ``param`` identifies the quantity as
    ``(discipline, parameter_category, parameter_number, level_type)`` —
    enough to pick e.g. 2 m temperature out of a multi-field file. Geometry is
    deliberately limited to ``nx``/``ny``/``scan_mode``; the projection is the
    caller's concern (the grid is fixed, see :mod:`forecast`).
    """

    reference_time: datetime
    param: tuple[int, int, int, int]
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


def _decode_simple_packing(
    section5: bytes, section7: bytes, n_values: int
) -> list[float]:
    """Unpack DRT 5.0: ``value = (R + X·2**E) / 10**D``.

    ``X`` is an ``nbits``-wide unsigned integer from the big-endian bit stream.
    """
    reference = struct.unpack(">f", section5[11:15])[0]
    binary_scale = _grib_int(section5, 15, 2)
    decimal_scale = _grib_int(section5, 17, 2)
    nbits = section5[19]

    factor = 10.0**-decimal_scale
    scale = (2.0**binary_scale) * factor
    base = reference * factor

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


def _decode_ieee(section5: bytes, section7: bytes, n_values: int) -> list[float]:
    """Unpack DRT 5.4: raw big-endian IEEE 754 floats.

    Precision octet: 1 = 32-bit, 2 = 64-bit. SHMÚ uses this only for a
    constant orography field, but decoding it keeps the "fail loud only on a
    *truly* unsupported template" contract intact (no field is silently
    dropped).
    """
    precision = section5[11]
    fmt = ">f" if precision == 1 else ">d"
    width = 4 if precision == 1 else 8
    payload = section7[5:]
    return [struct.unpack_from(fmt, payload, k * width)[0] for k in range(n_values)]


def _decode_values(
    template: int,
    section5: bytes,
    section7: bytes,
    bitmap: list[bool] | None,
    npts: int,
) -> tuple[float | None, ...]:
    """Decode Section 7 for a supported data-representation template."""
    n_values = sum(bitmap) if bitmap is not None else npts
    if template == _SIMPLE_PACKING:
        unpacked = _decode_simple_packing(section5, section7, n_values)
    else:  # _IEEE_PACKING — the only other member of _SUPPORTED_TEMPLATES
        unpacked = _decode_ieee(section5, section7, n_values)
    return _scatter(unpacked, bitmap)


def iter_fields(data: bytes) -> Iterator[Grib2Field]:
    """Yield every decoded field in a GRIB2 file (each ``GRIB…7777`` message).

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
        npts = nx = ny = scan_mode = 0
        data_template = -1
        bitmap: list[bool] | None = None
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
                param = (discipline, sec[9], sec[10], sec[22])
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
                    bits = sec[6:]
                    bitmap = [
                        bool((bits[k >> 3] >> (7 - (k & 7))) & 1) for k in range(npts)
                    ]
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

        yield Grib2Field(
            reference_time=reference_time,
            param=param,
            nx=nx,
            ny=ny,
            scan_mode=scan_mode,
            values=_decode_values(data_template, section5, section7, bitmap, npts),
        )
        pos = end
