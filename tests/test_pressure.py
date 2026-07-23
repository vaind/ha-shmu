"""Tests for the sea-level pressure reduction."""

from __future__ import annotations

import pytest

from custom_components.shmu.shmu_opendata.pressure import sea_level_pressure


def test_at_sea_level_is_identity() -> None:
    """A station already at 0 m needs no reduction."""
    assert sea_level_pressure(1013.0, 0.0, 15.0) == pytest.approx(1013.0)


def test_lowland_station_reduces_slightly() -> None:
    """Hurbanovo (115 m): QFE 1001.25 hPa at 15 °C -> ~1015 hPa QFF.

    Value computed from the barometric formula with the ICAO lapse rate; a
    change to the physics should fail this deliberately tight assertion.
    """
    result = sea_level_pressure(1001.25, 115.0, 15.0)
    assert result == pytest.approx(1014.98, abs=0.1)


def test_mountain_station_reduction_is_large() -> None:
    """Lomnický Štít (2635 m) reads far below sea level and reduces a lot.

    The reduction must lift the raw ~793 hPa into the sea-level range that the
    reading (a genuine high-pressure day) implies, well above the raw value.
    This is the exact confusion the feature fixes: a mountain barometer reading
    is not a headline "air pressure".
    """
    reduced = sea_level_pressure(792.8, 2635.0, 0.0)
    assert reduced is not None
    assert reduced > 1000.0
    assert reduced > 792.8


def test_reduction_is_temperature_sensitive() -> None:
    """Colder air is denser, so it reduces to a higher sea-level pressure."""
    cold = sea_level_pressure(950.0, 500.0, -10.0)
    warm = sea_level_pressure(950.0, 500.0, 30.0)
    assert cold is not None and warm is not None
    assert cold > warm


@pytest.mark.parametrize(
    ("pressure", "temperature"),
    [(None, 15.0), (1000.0, None), (None, None)],
)
def test_missing_inputs_return_none(
    pressure: float | None, temperature: float | None
) -> None:
    """The correction is not meaningful without both pressure and temperature."""
    assert sea_level_pressure(pressure, 300.0, temperature) is None
