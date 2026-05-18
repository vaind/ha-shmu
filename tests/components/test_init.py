"""Setup / entity tests with a stubbed SHMÚ client."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import CONF_IND_KLI, DOMAIN
from custom_components.shmu.shmu_opendata import (
    ForecastSnapshot,
    ObservationSnapshot,
    RadarFrame,
    RadarSnapshot,
    WarningsSnapshot,
    WebConditionsSnapshot,
)
from custom_components.shmu.shmu_opendata.client import _frame_label, _radar_snapshot
from custom_components.shmu.shmu_opendata.forecast import grid_index, parse_forecast
from custom_components.shmu.shmu_opendata.parsers import (
    parse_cap_alert,
    parse_observations,
)
from custom_components.shmu.shmu_opendata.radar import render_radar
from custom_components.shmu.shmu_opendata.website import parse_current_conditions

#: Forecast hours backed by the trimmed real GRIB2 fixtures.
_FCAST_FIXTURE_HOURS = (0, 1, 2, 24)


class _FakeClient:
    """Stand-in for ShmuClient returning canned, fixture-derived snapshots."""

    def __init__(self, load: Callable[[str], bytes]) -> None:
        self._load = load
        #: When True, the next snapshot omits the configured station.
        self.drop_station: int | None = None
        self._serial = 0

    async def async_get_observations(self, previous=None) -> ObservationSnapshot:
        observations = parse_observations(self._load("observations.json"))
        if self.drop_station is not None:
            observations.pop(self.drop_station, None)
        self._serial += 1
        return ObservationSnapshot(
            observations=observations,
            source=f"test-{self._serial}",
            fetched_at=datetime.now(UTC),
            published_at=None,
        )

    async def async_get_warnings(self, previous=None) -> WarningsSnapshot:
        return WarningsSnapshot(
            warnings=[parse_cap_alert(self._load("alert.cap.xml"))],
            source="test",
            fetched_at=datetime.now(UTC),
        )

    async def async_get_web_conditions(self) -> WebConditionsSnapshot:
        return WebConditionsSnapshot(
            conditions=parse_current_conditions(
                self._load("apocasie.html").decode("utf-8")
            ),
            fetched_at=datetime.now(UTC),
        )

    async def async_get_forecast(
        self,
        latitude: float,
        longitude: float,
        *,
        forecast_hours=None,
        previous=None,
    ) -> ForecastSnapshot:
        files = [(h, self._load(f"aladin_{h:03d}.grb")) for h in _FCAST_FIXTURE_HOURS]
        return ForecastSnapshot(
            steps=parse_forecast(files, latitude, longitude),
            run=datetime(2026, 5, 17, 12, tzinfo=UTC),
            source="test-run/20260517/1200",
            grid_point=grid_index(latitude, longitude),
            fetched_at=datetime.now(UTC),
        )

    async def async_get_radar(
        self, latitude, longitude, *, product="zmax", previous=None, tz=None
    ) -> RadarSnapshot:
        frames = []
        for m in ("10", "15", "20"):
            valid_at = datetime(2026, 5, 17, 20, int(m), tzinfo=UTC)
            frames.append(
                RadarFrame(
                    image=render_radar(
                        self._load("radar_zmax.hdf"),
                        latitude,
                        longitude,
                        label=_frame_label(valid_at, tz),
                    ),
                    source=f"test-run/20260517/T_PABV22_C_LZIB_2026051720{m}00.hdf",
                    valid_at=valid_at,
                )
            )
        return _radar_snapshot(frames, product)


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="11858",
        title="Hurbanovo",
        data={CONF_IND_KLI: 11858},
    )
    config_entry.add_to_hass(hass)
    return config_entry


async def test_setup_creates_entities(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    # Polling is driven on the upstream UTC grid, not a fixed interval.
    assert entry.runtime_data.update_interval is None

    weather = hass.states.get("weather.hurbanovo")
    assert weather is not None
    # Website says Zamračené/Dážď for Hurbanovo -> rainy.
    assert weather.state == "rainy"
    assert weather.attributes["temperature"] == 12.1

    # Values come from the latest minute (06:52) of the 3 records for 11858.
    assert hass.states.get("sensor.hurbanovo_temperature").state == "12.1"
    assert hass.states.get("sensor.hurbanovo_pressure").state == "1001.2"

    # The only warning's polygon is around Bratislava; Hurbanovo is outside it.
    assert hass.states.get("binary_sensor.hurbanovo_weather_warning").state == "off"
    assert hass.states.get("sensor.hurbanovo_warning_level").state == "none"


async def test_observation_carried_forward_across_dropout(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    client = _FakeClient(load)
    with patch("custom_components.shmu.ShmuClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.hurbanovo_temperature").state == "12.1"

    # The next snapshot omits the station entirely (a one-cycle dropout).
    client.drop_station = 11858
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    # Last reading is carried forward — no flicker to unknown/unavailable.
    temperature = hass.states.get("sensor.hurbanovo_temperature")
    assert temperature.state == "12.1"
    assert hass.states.get("weather.hurbanovo").state == "rainy"


async def test_unload(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
