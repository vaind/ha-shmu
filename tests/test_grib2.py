"""Tests for the pure-Python GRIB2 decoder (trimmed real fixtures)."""

from __future__ import annotations

import pytest

from custom_components.shmu.shmu_opendata.exceptions import ShmuDataError
from custom_components.shmu.shmu_opendata.grib2 import iter_fields, iter_messages

# Surface params we rely on, by (discipline, category, number, level type).
_T2M = (0, 0, 0, 103)
_TCC = (192, 128, 164, 1)
_OROGRAPHY = (0, 3, 5, 1)  # the only DRT 5.4 (IEEE) message, hour 000 only
_T_PRESSURE = (0, 0, 0, 100)  # temperature, published on five pressure levels


def test_iter_fields_decodes_simple_packing(fixture) -> None:
    fields = list(iter_fields(fixture("aladin_001.grb")))
    assert fields, "expected at least one field"

    by_param = {f.param: f for f in fields}
    assert _T2M in by_param

    t2m = by_param[_T2M]
    assert t2m.nx == 94
    assert t2m.ny == 48
    assert t2m.scan_mode == 0x40
    assert len(t2m.values) == t2m.nx * t2m.ny
    # All fields in this file share the run reference time.
    assert t2m.reference_time.isoformat() == "2026-05-17T12:00:00+00:00"

    present = [v for v in t2m.values if v is not None]
    # A bitmap masks the rectangle down to the Slovakia sub-domain.
    assert 0 < len(present) < len(t2m.values)
    # Plausible mid-May 2 m temperatures (Kelvin) over Slovakia.
    assert all(250.0 < v < 320.0 for v in present)


def test_iter_fields_decodes_ieee_orography(fixture) -> None:
    """Hour 000 carries the orography as DRT 5.4 IEEE float."""
    by_param = {f.param: f for f in iter_fields(fixture("aladin_000.grb"))}
    assert _OROGRAPHY in by_param
    heights = [v for v in by_param[_OROGRAPHY].values if v is not None]
    # Slovakia surface heights span roughly sea level to the High Tatras.
    assert heights
    assert all(-10.0 < h < 2700.0 for h in heights)


def test_value_at_matches_flat_index(fixture) -> None:
    field = next(iter_fields(fixture("aladin_002.grb")))
    assert field.value_at(5, 3) == field.values[3 * field.nx + 5]


def _section_offset(data: bytes | bytearray, number: int) -> int:
    """Offset of the first message's first section ``number``."""
    pos = 16
    while data[pos + 4] != number:
        pos += int.from_bytes(data[pos : pos + 4], "big")
    return pos


# Both readers share one parse, so every format check must fire for each —
# including iter_messages, where an unsupported message is never unpacked.
_READERS = pytest.mark.parametrize("reader", [iter_fields, iter_messages])


@_READERS
def test_unsupported_template_raises_loudly(fixture, reader) -> None:
    """A non-5.0/5.4 packing template must fail, never silently mislead."""
    data = bytearray(fixture("aladin_002.grb"))
    # Rewrite the first Section 5's template number to 40 (JPEG2000).
    pos = _section_offset(data, 5)
    data[pos + 9 : pos + 11] = (40).to_bytes(2, "big")
    with pytest.raises(ShmuDataError, match=r"5\.40"):
        list(reader(bytes(data)))


@_READERS
def test_unsupported_bitmap_indicator_raises(fixture, reader) -> None:
    data = bytearray(fixture("aladin_002.grb"))
    data[_section_offset(data, 6) + 5] = 254  # "reuse the previous bitmap"
    with pytest.raises(ShmuDataError, match="bitmap indicator 254"):
        list(reader(bytes(data)))


@_READERS
def test_short_section7_raises(fixture, reader) -> None:
    """Too few packed bytes for the bitmap's points must not read past them.

    Point access would otherwise index into the next section's bytes (or
    past the end) and hand back a plausible-looking wrong number.
    """
    data = bytearray(fixture("aladin_002.grb"))
    pos = _section_offset(data, 5)
    data[pos + 19] = 32  # claim 32-bit values: more than Section 7 holds
    with pytest.raises(ShmuDataError, match="Section 7"):
        list(reader(bytes(data)))


@_READERS
def test_unsupported_ieee_precision_raises(fixture, reader) -> None:
    """DRT 5.4 precision 3 (128-bit) has no struct format; never guess one."""
    data = bytearray(fixture("aladin_000.grb"))
    pos = 0
    while True:  # the orography message is the only DRT 5.4 one
        sec5 = pos + _section_offset(data[pos:], 5)
        if int.from_bytes(data[sec5 + 9 : sec5 + 11], "big") == 4:
            break
        pos += int.from_bytes(data[pos + 8 : pos + 16], "big")
    data[sec5 + 11] = 3
    with pytest.raises(ShmuDataError, match="precision 3"):
        list(reader(bytes(data)))


@pytest.mark.parametrize(
    "name",
    [
        "aladin_000.grb",
        "aladin_001.grb",
        "aladin_002.grb",
        "aladin_024.grb",
        "aladin_upper_000.grb",
    ],
)
def test_point_decode_matches_full_decode(fixture, name) -> None:
    """Unpacking one point must be bit-identical to unpacking the whole grid.

    The forecast reads only through the point path, while the fixtures' pinned
    values were established through the full one — so this ties every message
    (both packing templates, every bit width, masked and unmasked points) of
    the point path back to them.
    """
    messages = list(iter_messages(fixture(name)))
    assert messages
    for message in messages:
        full = message.decode()
        assert full.values == tuple(
            message.value_at(i, j) for j in range(message.ny) for i in range(message.nx)
        ), (message.param, message.level)


def test_point_decode_rejects_off_grid_points(fixture) -> None:
    """Off-grid indices must not wrap around (Python negative indexing)."""
    message = next(iter_messages(fixture("aladin_002.grb")))
    for i, j in [(-1, 0), (0, -1), (message.nx, 0), (0, message.ny)]:
        with pytest.raises(IndexError):
            message.value_at(i, j)


def test_truncated_message_raises(fixture) -> None:
    with pytest.raises(ShmuDataError, match="Truncated"):
        list(iter_fields(fixture("aladin_002.grb")[:-200]))


def test_non_grib_payload_raises() -> None:
    with pytest.raises(ShmuDataError, match="Expected 'GRIB'"):
        list(iter_fields(b"<html>not a grib file</html>"))


def test_pressure_level_messages_are_addressable(fixture) -> None:
    """Five same-``param`` messages differ only by level — and must survive it.

    Temperature on the 925/850/700/500/250 hPa levels shares one ``param``, so
    without the level they collapse onto a single key (issue #44).
    """
    fields = list(iter_fields(fixture("aladin_upper_000.grb")))
    temperatures = [f for f in fields if f.param == _T_PRESSURE]
    assert [f.level for f in temperatures] == [
        92500.0,
        85000.0,
        70000.0,
        50000.0,
        25000.0,
    ]
    # Distinct fields, not five views of one message.
    assert len({f.values for f in temperatures}) == len(temperatures)


def test_surface_message_reports_its_own_level(fixture) -> None:
    by_param = {f.param: f for f in iter_fields(fixture("aladin_001.grb"))}
    assert by_param[_T2M].level == 2.0  # the 2 m screen
    assert by_param[(0, 2, 2, 103)].level == 10.0  # 10 m wind


def test_missing_level_is_none_not_an_absurd_exponent(fixture) -> None:
    """GRIB's all-ones "missing" level must not decode as ``10**127``."""
    data = bytearray(fixture("aladin_002.grb"))
    pos = 16
    while data[pos + 4] != 4:  # first Section 4 (product definition)
        pos += int.from_bytes(data[pos : pos + 4], "big")
    data[pos + 23] = 0xFF  # scale factor
    data[pos + 24 : pos + 28] = b"\xff\xff\xff\xff"  # scaled value
    assert next(iter_fields(bytes(data))).level is None
