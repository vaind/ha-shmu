"""Tests for the pure-Python GRIB2 decoder (trimmed real fixtures)."""

from __future__ import annotations

import pytest

from custom_components.shmu.shmu_opendata.exceptions import ShmuDataError
from custom_components.shmu.shmu_opendata.grib2 import iter_fields

# Surface params we rely on, by (discipline, category, number, level type).
_T2M = (0, 0, 0, 103)
_TCC = (192, 128, 164, 1)
_OROGRAPHY = (0, 3, 5, 1)  # the only DRT 5.4 (IEEE) message, hour 000 only


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


def test_unsupported_template_raises_loudly(fixture) -> None:
    """A non-5.0/5.4 packing template must fail, never silently mislead."""
    data = bytearray(fixture("aladin_002.grb"))
    # Find the first Section 5 and rewrite its template number to 40 (JPEG2000).
    pos = 16
    while data[pos + 4] != 5:
        pos += int.from_bytes(data[pos : pos + 4], "big")
    data[pos + 9 : pos + 11] = (40).to_bytes(2, "big")
    with pytest.raises(ShmuDataError, match=r"5\.40"):
        list(iter_fields(bytes(data)))


def test_truncated_message_raises(fixture) -> None:
    with pytest.raises(ShmuDataError, match="Truncated"):
        list(iter_fields(fixture("aladin_002.grb")[:-200]))


def test_non_grib_payload_raises() -> None:
    with pytest.raises(ShmuDataError, match="Expected 'GRIB'"):
        list(iter_fields(b"<html>not a grib file</html>"))
