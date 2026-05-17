"""Tests for the WMO 4680 (wawa) -> HA condition mapping."""

from __future__ import annotations

import pytest

from custom_components.shmu.shmu_opendata.conditions import condition_from_weather_code


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (None, None),  # no code, no precip -> unknown
        (0, None),  # "no significant weather": real value, sky unknown
        (3, None),
        (4, "fog"),  # haze/smoke/dust
        (10, "fog"),  # mist
        (12, "lightning"),  # distant lightning
        (18, "windy"),  # squalls
        (25, None),  # preceding-hour precipitation, not now
        (30, "fog"),  # fog
        (40, "rainy"),  # precipitation, unknown type
        (42, "pouring"),  # heavy precipitation
        (51, "rainy"),  # slight drizzle
        (53, "pouring"),  # heavy drizzle
        (55, "snowy-rainy"),  # freezing drizzle
        (61, "rainy"),  # slight rain
        (63, "pouring"),  # heavy rain
        (66, "snowy-rainy"),  # freezing rain
        (71, "snowy"),  # snow
        (75, "hail"),  # ice pellets
        (82, "pouring"),  # violent rain showers
        (84, "snowy-rainy"),  # mixed showers
        (86, "snowy"),  # snow showers
        (89, "hail"),  # hail showers
        (91, "lightning"),  # thunderstorm, no precip
        (95, "lightning-rainy"),  # thunderstorm with rain
        (96, "hail"),  # thunderstorm with hail
    ],
)
def test_known_codes(code: int | None, expected: str | None) -> None:
    assert condition_from_weather_code(code) == expected


@pytest.mark.parametrize("code", [7, 15, 19, 45, 49])
def test_uncovered_codes_are_unknown_not_exceptional(code: int) -> None:
    # Honest "unknown" rather than fabricating an alarming "exceptional" icon.
    assert condition_from_weather_code(code) is None
    assert condition_from_weather_code(code, precipitation=0.4) == "rainy"


def test_precipitation_hint_only_when_code_is_uninformative() -> None:
    # Uninformative code + measured precip -> rainy.
    assert condition_from_weather_code(0, precipitation=0.4) == "rainy"
    assert condition_from_weather_code(None, precipitation=0.4) == "rainy"
    # An informative code is never overridden by the precip hint.
    assert condition_from_weather_code(71, precipitation=0.4) == "snowy"
    # Zero precipitation is not a hint.
    assert condition_from_weather_code(0, precipitation=0.0) is None
