"""Diagnostics tests."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import CONF_IND_KLI, DOMAIN
from custom_components.shmu.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)

from .test_init import _FakeClient


async def test_config_entry_diagnostics(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="11858", title="Hurbanovo", data={CONF_IND_KLI: 11858}
    )
    entry.add_to_hass(hass)

    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["station"]["ind_kli"] == 11858
    assert diag["station"]["name"] == "Hurbanovo"
    assert diag["coordinator"]["last_update_success"] is True
    # Website said Zamračené/Dážď -> rainy via the website source.
    assert diag["derived_condition"] == {"condition": "rainy", "source": "website"}
    assert diag["observations"]["station_present"] is True
    # The full original SHMÚ row is included for debugging.
    assert diag["observations"]["raw_record"]["stav_poc"] == 61
    assert diag["web_conditions"]["station"]["weather_text"] == "Dážď"
    # No active warning covers Hurbanovo (polygon is around Bratislava).
    assert diag["warnings"]["active_for_station"] == []
    # The user's HA home coordinates must never leak into the dump.
    assert "latitude" not in diag["coordinator"]
    assert "home" not in repr(diag).lower()


async def test_device_diagnostics_matches_config_entry(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="11858", title="Hurbanovo", data={CONF_IND_KLI: 11858}
    )
    entry.add_to_hass(hass)

    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "11858")})
    assert device is not None

    device_diag = await async_get_device_diagnostics(hass, entry, device)
    entry_diag = await async_get_config_entry_diagnostics(hass, entry)
    # One device per entry: the device dump is the full config-entry dump.
    assert device_diag == entry_diag
    assert device_diag["station"]["ind_kli"] == 11858
