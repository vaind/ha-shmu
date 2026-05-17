"""Tests for ALADIN grid projection, point extraction and field mapping."""

from __future__ import annotations

import pytest

from custom_components.shmu.shmu_opendata.forecast import (
    derive_condition,
    grid_index,
    nearest_unmasked_index,
    parse_forecast,
)
from custom_components.shmu.shmu_opendata.grib2 import iter_fields


@pytest.mark.parametrize(
    ("lat", "lon", "expected"),
    [
        (48.1717, 17.2, (6, 11)),  # Bratislava - Letisko (SW)
        (48.6722, 21.2225, (71, 25)),  # Košice (E)
        (49.0689, 20.2456, (55, 34)),  # Poprad (N)
    ],
)
def test_grid_index_known_stations(lat, lon, expected) -> None:
    """Forward Lambert projection is a fixed grid -> deterministic indices."""
    i, j = grid_index(lat, lon)
    assert (i, j) == expected
    assert 0 <= i < 94
    assert 0 <= j < 48


def test_grid_index_clamps_far_point() -> None:
    i, j = grid_index(0.0, 0.0)  # far outside the domain
    assert 0 <= i < 94
    assert 0 <= j < 48


def test_nearest_unmasked_returns_a_value(fixture) -> None:
    field = next(iter_fields(fixture("aladin_001.grb")))
    i, j = nearest_unmasked_index(field, 48.1717, 17.2)
    assert field.value_at(i, j) is not None


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"cloud_coverage": None, "precipitation": None}, None),
        ({"cloud_coverage": 5.0, "precipitation": 0.0}, "sunny"),
        ({"cloud_coverage": 50.0, "precipitation": 0.0}, "partlycloudy"),
        ({"cloud_coverage": 95.0, "precipitation": 0.0}, "cloudy"),
        ({"cloud_coverage": 100.0, "precipitation": 0.01}, "cloudy"),  # trace
        ({"cloud_coverage": 100.0, "precipitation": 0.5, "temperature": 10.0}, "rainy"),
        (
            {"cloud_coverage": 100.0, "precipitation": 3.0, "temperature": 10.0},
            "pouring",
        ),
        (
            {"cloud_coverage": 100.0, "precipitation": 0.5, "temperature": -1.0},
            "snowy",
        ),
        (
            {"cloud_coverage": 100.0, "precipitation": 0.5, "temperature": 1.5},
            "snowy-rainy",
        ),
        (
            {
                "cloud_coverage": 100.0,
                "precipitation": 0.5,
                "temperature": 18.0,
                "cape": 400.0,
            },
            "lightning-rainy",
        ),
    ],
)
def test_derive_condition(kwargs, expected) -> None:
    full = {
        "cloud_coverage": None,
        "precipitation": None,
        "temperature": None,
        "cape": None,
        **kwargs,
    }
    assert derive_condition(**full) == expected


def test_parse_forecast_steps_and_precip_delta(fixture) -> None:
    files = [
        (0, fixture("aladin_000.grb")),
        (1, fixture("aladin_001.grb")),
        (2, fixture("aladin_002.grb")),
    ]
    steps = parse_forecast(files, 48.1717, 17.2)

    assert [s.time.isoformat() for s in steps] == [
        "2026-05-17T12:00:00+00:00",
        "2026-05-17T13:00:00+00:00",
        "2026-05-17T14:00:00+00:00",
    ]
    # Temperatures converted K -> °C and physically sane.
    assert steps[0].temperature == pytest.approx(14.32, abs=0.1)
    assert all(-30.0 < s.temperature < 45.0 for s in steps)

    # Total precip is accumulated since run start: hour 0 has no accumulation
    # window, hour 1 reports the first amount, hour 2 is the *delta*.
    assert steps[0].precipitation is None
    assert steps[1].precipitation == pytest.approx(0.166, abs=0.01)
    assert steps[2].precipitation == pytest.approx(0.019, abs=0.01)
    assert steps[2].precipitation >= 0.0  # delta never negative

    assert steps[1].condition == "rainy"  # wet step
    assert steps[0].condition == "cloudy"  # dry, full cloud
    assert 0.0 <= steps[0].cloud_coverage <= 100.0
    assert steps[0].wind_speed is not None and steps[0].wind_speed >= 0.0
    assert steps[0].wind_bearing is not None
    assert 0.0 <= steps[0].wind_bearing < 360.0


def test_parse_forecast_resets_accumulation_per_run(fixture) -> None:
    """Feeding a later hour first must not yield a negative precip delta."""
    files = [
        (2, fixture("aladin_002.grb")),
        (1, fixture("aladin_001.grb")),  # smaller accumulation than hour 2
    ]
    steps = parse_forecast(files, 48.1717, 17.2)
    assert steps[1].precipitation == 0.0  # clamped, not negative
