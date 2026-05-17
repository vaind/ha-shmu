"""Tests for the pure-Python ODIM_H5 reader (trimmed real-derived fixture)."""

from __future__ import annotations

import pytest

from custom_components.shmu.shmu_opendata.exceptions import ShmuDataError
from custom_components.shmu.shmu_opendata.odim import read_odim


def test_reads_dbzh_composite(fixture) -> None:
    o = read_odim(fixture("radar_zmax.hdf"))
    assert o.quantity == "DBZH"
    assert o.product == "MAX"
    assert o.dtype == "u8"
    assert (o.width, o.height) == (64, 48)
    assert len(o.raw) == o.width * o.height
    # SHMÚ DBZH scale (preserved from the real file the fixture derives from).
    assert round(o.gain, 5) == 0.50197
    assert round(o.offset, 5) == -32.50197
    assert o.nodata == -1.0
    assert o.undetect == 0.0
    # Real ODIM corner box: SW ≈ (46, 13.6), NE ≈ (50.7, 23.8).
    assert 45.0 < o.ll_lat < 47.0
    assert 13.0 < o.ll_lon < 14.0
    assert 50.0 < o.ur_lat < 51.0
    assert 23.0 < o.ur_lon < 24.0
    assert o.projdef.startswith("+proj=merc")


def test_reads_float32_dataset(fixture) -> None:
    """The reader stays honest about the non-reflectivity float product."""
    o = read_odim(fixture("radar_unsupported.hdf"))
    assert o.quantity == "ACRR"
    assert o.dtype == "f32"
    assert len(o.raw) == o.width * o.height * 4


def test_non_hdf5_payload_raises() -> None:
    with pytest.raises(ShmuDataError, match="Not an HDF5 file"):
        read_odim(b"<html>not hdf5</html>")


def test_truncated_file_raises(fixture) -> None:
    """A cut-off file trips a structural guard — loud, never a wrong image."""
    with pytest.raises(ShmuDataError):
        read_odim(fixture("radar_zmax.hdf")[:200])


def test_unsupported_superblock_version_raises(fixture) -> None:
    data = bytearray(fixture("radar_zmax.hdf"))
    data[8] = 3  # superblock version byte
    with pytest.raises(ShmuDataError, match="superblock version"):
        read_odim(bytes(data))


def test_unsupported_offset_size_raises() -> None:
    """A valid signature but a non-8 offset/length size fails cleanly."""
    payload = b"\x89HDF\r\n\x1a\n" + bytes(16)  # superblock v0, off/len = 0
    with pytest.raises(ShmuDataError, match="offset/length size"):
        read_odim(payload)
