"""Tests for ALADIN grid projection, point extraction and field mapping."""

from __future__ import annotations

import pytest

from custom_components.shmu.shmu_opendata.exceptions import ShmuDataError
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
        # A trace also vetoes the thunderstorm branch even with high CAPE:
        # ALADIN over-predicts convection, so a dry step must not surface a
        # phantom lightning-rainy.
        (
            {
                "cloud_coverage": 100.0,
                "precipitation": 0.03,
                "temperature": 18.0,
                "cape": 400.0,
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


def test_parse_forecast_steps_and_hourly_precipitation(fixture) -> None:
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

    # Each file holds its own hour's precipitation, as its Section 4 states
    # (template 4.8, accumulation over the hour ending at the valid time), so
    # hour 2 is 0.185 mm and not its 0.019 mm rise over hour 1. Hour 0 has no
    # precipitation message at all.
    assert steps[0].precipitation is None
    assert steps[1].precipitation == pytest.approx(0.166, abs=0.001)
    assert steps[2].precipitation == pytest.approx(0.185, abs=0.001)
    assert [s.span_hours for s in steps] == [1.0, 1.0, 1.0]

    assert steps[1].condition == "rainy"  # wet step
    assert steps[2].condition == "rainy"
    assert steps[0].condition == "cloudy"  # dry, full cloud
    assert 0.0 <= steps[0].cloud_coverage <= 100.0
    assert steps[0].wind_speed is not None and steps[0].wind_speed >= 0.0
    assert steps[0].wind_bearing is not None
    assert 0.0 <= steps[0].wind_bearing < 360.0


def test_parse_forecast_window_comes_from_the_file_not_the_gap(fixture) -> None:
    """A skipped hour must not widen the next step's window.

    Reading every third file used to make a step's window the 3 h gap to its
    predecessor, though the file holds only the hour ending at its valid time.
    """
    with_gap = parse_forecast(
        [(0, fixture("aladin_000.grb")), (2, fixture("aladin_002.grb"))],
        48.1717,
        17.2,
    )
    alone = parse_forecast([(2, fixture("aladin_002.grb"))], 48.1717, 17.2)

    for steps in (with_gap, alone):
        assert steps[-1].precipitation == pytest.approx(0.185, abs=0.001)
        assert steps[-1].span_hours == 1.0


def _with_precipitation_octet(payload: bytes, index: int, value: int) -> bytes:
    """``payload`` with byte ``index`` of its precipitation Section 4 replaced."""
    data = bytearray(payload)
    pos = 0
    while (pos := data.find(b"GRIB", pos)) >= 0:
        end = pos + int.from_bytes(data[pos + 8 : pos + 16])
        sec = pos + 16
        while data[sec + 4] != 4:
            sec += int.from_bytes(data[sec : sec + 4])
        if (data[pos + 6], data[sec + 9], data[sec + 10]) == (0, 1, 193):
            data[sec + index] = value
            return bytes(data)
        pos = end
    raise AssertionError("no precipitation message")


def test_parse_forecast_rejects_precipitation_that_is_not_an_accumulation(
    fixture,
) -> None:
    """A changed statistic must fail loudly, not scale the forecast wrongly."""
    # Octet 47 is the statistic (WMO code table 4.10), and 0 is an average.
    payload = _with_precipitation_octet(fixture("aladin_001.grb"), 46, 0)
    with pytest.raises(ShmuDataError, match="not an accumulation"):
        parse_forecast([(1, payload)], 48.1717, 17.2)


def test_parse_forecast_rejects_a_window_longer_than_the_hour(fixture) -> None:
    """A running total ending at the step would count again in every step.

    Octets 50-53 hold the window's length, so this is a 2 h total from the
    run start, the shape the field was once wrongly assumed to have.
    """
    payload = _with_precipitation_octet(fixture("aladin_002.grb"), 52, 2)
    with pytest.raises(ShmuDataError, match="covers 2:00:00 ending at"):
        parse_forecast([(2, payload)], 48.1717, 17.2)


def test_parse_forecast_rejects_a_window_ending_off_the_step(fixture) -> None:
    """A file whose window ends elsewhere than its name says is not this hour's."""
    with pytest.raises(ShmuDataError, match="ending at 2026-05-17 13:00"):
        parse_forecast([(2, fixture("aladin_001.grb"))], 48.1717, 17.2)


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


def _profile_at(
    payload: bytes, latitude: float, longitude: float, *, anchored: bool = True
):
    """The module's vertical profile at a point, straight from a real file.

    ``anchored=False`` stands in for a run whose hour-000 file (the only one
    carrying the terrain) never reached us.
    """
    fields = {(*f.param, f.level): f for f in iter_fields(payload)}
    i, j = nearest_unmasked_index(fields[_T2M], latitude, longitude)

    def value(key):
        field = fields.get(key)
        return None if field is None else field.value_at(i, j)

    surface = value(_T2M)
    return _vertical_profile(
        value,
        None if surface is None else surface - 273.15,
        value(_OROGRAPHY) if anchored else None,
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


def test_no_profile_without_the_surface_anchor(fixture) -> None:
    """Without the terrain there is no profile — and so no freezing level.

    Everything below the lowest pressure level is unobserved, which is exactly
    where a winter freezing level sits. An unanchored profile would let a
    sub-zero 925 hPa point pose as the surface and hand back its own height,
    a number the data cannot support; unknown is the honest answer.
    """
    payload = fixture("aladin_upper_000.grb")
    assert _profile_at(payload, 48.1717, 17.2, anchored=False) == []
    assert derive_freezing_level([]) is None
    # The 850 hPa temperature is a plain lookup and stays available.
    (step,) = parse_forecast([(0, payload)], 48.1717, 17.2)
    assert step.temperature_850hpa is not None
