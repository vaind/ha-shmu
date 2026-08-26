"""Tests for ALADIN grid projection, point extraction and field mapping."""

from __future__ import annotations

import pytest

from custom_components.shmu.shmu_opendata.forecast import (
    _OROGRAPHY,
    _T2M,
    _vertical_profile,
    derive_condition,
    derive_freezing_level,
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
        # A 3-hourly step (hours=3) is classified by its per-hour rate, not its
        # raw total: 3 mm over 3 h is 1 mm/h → "rainy", not "pouring".
        (
            {
                "cloud_coverage": 100.0,
                "precipitation": 3.0,
                "temperature": 10.0,
                "hours": 3.0,
            },
            "rainy",
        ),
        # 0.1 mm over 3 h is a trace rate (0.033 mm/h) → dry sky, not "rainy".
        (
            {"cloud_coverage": 100.0, "precipitation": 0.1, "hours": 3.0},
            "cloudy",
        ),
        # Trace rate also vetoes the thunderstorm branch even with high CAPE:
        # ALADIN over-predicts convection, so a dry 3-hourly step must not
        # surface a phantom lightning-rainy.
        (
            {
                "cloud_coverage": 100.0,
                "precipitation": 0.1,
                "temperature": 18.0,
                "cape": 400.0,
                "hours": 3.0,
            },
            "cloudy",
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


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        # Crossing inside a layer: halfway between 1000 m (+2 °C) and 2000 m
        # (-2 °C).
        ([(1000.0, 2.0), (2000.0, -2.0)], 1500.0),
        # Surface already at/below freezing: the freezing level *is* the ground.
        ([(600.0, -3.0), (1500.0, -8.0)], 600.0),
        ([(600.0, 0.0), (1500.0, -8.0)], 600.0),
        # Valley inversion — two crossings; the lowest is the one that decides
        # what reaches the ground.
        (
            [(500.0, 1.0), (800.0, -1.0), (1200.0, 3.0), (2500.0, -5.0)],
            650.0,
        ),
        # Nothing freezing anywhere in the profile.
        ([(500.0, 12.0), (3000.0, 4.0)], None),
        # Not a profile: a single reading cannot pin a freezing level, even a
        # sub-zero one.
        ([(500.0, -4.0)], None),
        ([], None),
    ],
)
def test_derive_freezing_level(profile, expected) -> None:
    result = derive_freezing_level(profile)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected, abs=0.5)


def _profile_at(payload: bytes, latitude: float, longitude: float):
    """The module's vertical profile at a point, straight from a real file."""
    fields = {(*f.param, f.level): f for f in iter_fields(payload)}
    i, j = nearest_unmasked_index(fields[_T2M], latitude, longitude)

    def value(key):
        field = fields.get(key)
        return None if field is None else field.value_at(i, j)

    surface = value(_T2M)
    return _vertical_profile(
        value,
        None if surface is None else surface - 273.15,
        value(_OROGRAPHY),
    )


def test_parse_forecast_reads_the_upper_air(fixture) -> None:
    """850 hPa temperature and the freezing level at a lowland point.

    The fixture is a real hour-000 file (2026-08-26 06 UTC), so the numbers are
    a late-August afternoon over Bratislava: an air mass around +12 °C at
    850 hPa and a freezing level a few kilometres up.
    """
    (step,) = parse_forecast([(0, fixture("aladin_upper_000.grb"))], 48.1717, 17.2)

    assert step.temperature_850hpa == pytest.approx(12.0, abs=0.5)
    assert step.freezing_level == pytest.approx(3610.0, abs=50.0)
    # Well above the terrain and inside the troposphere.
    assert 1000.0 < step.freezing_level < 5000.0


def test_upper_air_absent_from_surface_only_files(fixture) -> None:
    """Files without the pressure levels yield ``None``, never a wrong number."""
    (step,) = parse_forecast([(1, fixture("aladin_001.grb"))], 48.1717, 17.2)
    assert step.temperature_850hpa is None
    assert step.freezing_level is None
    # …while every surface field still decodes: a wrong level constant would
    # fail *silently* as None, so assert them all (issue #44 re-keyed them).
    assert step.temperature is not None
    assert step.precipitation is not None
    assert step.wind_speed is not None
    assert step.wind_gust is not None
    assert step.wind_bearing is not None
    assert step.pressure is not None
    assert step.cloud_coverage is not None
    assert step.cape is not None


def test_profile_starts_at_the_screen_over_the_terrain(fixture) -> None:
    profile = _profile_at(fixture("aladin_upper_000.grb"), 48.1717, 17.2)
    # Lowland point: the terrain is below 925 hPa, so all five levels are kept
    # on top of the 2 m anchor.
    assert len(profile) == 6
    assert profile[0][0] == pytest.approx(118.0, abs=5.0)  # ~116 m terrain + 2
    assert [h for h, _ in profile] == sorted(h for h, _ in profile)


def test_profile_drops_below_ground_levels(fixture) -> None:
    """A mountain grid point sits *above* 925 hPa, whose values are fiction.

    ALADIN extrapolates pressure levels below the model terrain; at a Chopok
    point (terrain ~1501 m) the 925 hPa surface is at ~816 m, i.e. underground.
    Interpolating a 0 °C crossing through that air would place the freezing
    level below the ground it is measured from.
    """
    profile = _profile_at(fixture("aladin_upper_000.grb"), 48.9439, 19.5919)
    terrain = profile[0][0]
    assert terrain == pytest.approx(1503.0, abs=5.0)
    assert len(profile) == 5  # 925 hPa dropped, the other four kept
    assert all(height > terrain for height, _ in profile[1:])
