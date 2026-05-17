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
    ObservationSnapshot,
    WarningsSnapshot,
    WebConditionsSnapshot,
)
from custom_components.shmu.shmu_opendata.parsers import (
    parse_cap_alert,
    parse_observations,
)
from custom_components.shmu.shmu_opendata.website import parse_current_conditions


class _FakeClient:
    """Stand-in for ShmuClient returning canned, fixture-derived snapshots."""

    def __init__(self, load: Callable[[str], bytes]) -> None:
        self._load = load

    async def async_get_observations(self, previous=None) -> ObservationSnapshot:
        return ObservationSnapshot(
            observations=parse_observations(self._load("observations.json")),
            source="test",
            fetched_at=datetime.now(UTC),
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


async def test_unload(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
