"""Weather forecast tests (ALADIN model via the stubbed client)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from unittest.mock import patch

import pytest
from homeassistant.components.weather import WeatherEntityFeature
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import CONF_IND_KLI, DOMAIN
from custom_components.shmu.diagnostics import async_get_config_entry_diagnostics

from .test_init import _FakeClient


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> MockConfigEntry:
    # Pin the zone so local-day grouping of the daily forecast is deterministic.
    await hass.config.async_set_time_zone("Europe/Bratislava")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="11858",
        title="Hurbanovo",
        data={CONF_IND_KLI: 11858},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _forecasts(hass: HomeAssistant, kind: str) -> list[dict]:
    result = await hass.services.async_call(
        "weather",
        "get_forecasts",
        {"entity_id": "weather.hurbanovo", "type": kind},
        blocking=True,
        return_response=True,
    )
    return result["weather.hurbanovo"]["forecast"]


async def test_weather_supports_forecast_features(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    state = hass.states.get("weather.hurbanovo")
    assert state is not None
    feats = state.attributes["supported_features"]
    assert feats & WeatherEntityFeature.FORECAST_HOURLY
    assert feats & WeatherEntityFeature.FORECAST_DAILY


async def test_hourly_forecast_shape_and_values(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    hourly = await _forecasts(hass, "hourly")
    # Fixtures cover forecast hours 0, 1, 2, 24.
    assert len(hourly) == 4
    assert [f["datetime"] for f in hourly] == sorted(f["datetime"] for f in hourly)

    first = hourly[0]
    assert datetime.fromisoformat(first["datetime"])  # parseable, tz-aware
    assert -30.0 < first["temperature"] < 45.0
    assert first["condition"] is not None
    assert 0 <= first["cloud_coverage"] <= 100
    assert first["wind_speed"] >= 0.0
    # Hour 1 of this real run is a wet step.
    assert hourly[1]["precipitation"] >= 0.0
    assert any(f["condition"] == "rainy" for f in hourly)


async def test_daily_forecast_aggregates_by_local_day(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    daily = await _forecasts(hass, "daily")
    # Hours 0/1/2 fall on 2026-05-17 (local), hour 24 on 2026-05-18.
    assert len(daily) == 2
    day0 = daily[0]
    assert day0["datetime"].startswith("2026-05-17")
    assert day0["templow"] <= day0["temperature"]  # low <= high
    assert day0["precipitation"] >= 0.0
    assert day0["condition"] is not None
    assert daily[1]["datetime"].startswith("2026-05-18")


async def test_diagnostics_includes_forecast_provenance(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    diag = await async_get_config_entry_diagnostics(hass, setup_entry)
    fc = diag["forecast"]
    assert fc is not None
    assert fc["source"] == "test-run/20260517/1200"
    assert fc["step_count"] == 4
    assert len(fc["grid_point"]) == 2
    assert fc["first_step"] is not None
