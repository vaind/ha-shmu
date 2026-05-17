"""Config-flow tests."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import CONF_IND_KLI, DOMAIN


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_IND_KLI: "11858"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hurbanovo"
    assert result["data"] == {CONF_IND_KLI: 11858}


async def test_user_flow_defaults_to_nearest_station(hass: HomeAssistant) -> None:
    # Place "home" right by Košice; its ind_kli must be the preselected default.
    hass.config.latitude = 48.7164
    hass.config.longitude = 21.2611

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    schema = result["data_schema"].schema
    key = next(iter(schema))
    assert key.default() == "11968"  # Košice


async def test_duplicate_station_is_aborted(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id="11858", data={CONF_IND_KLI: 11858}
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_IND_KLI: "11858"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
