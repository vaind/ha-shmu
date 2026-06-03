"""Config- and options-flow tests."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import (
    CONF_IND_KLI,
    CONF_LOCATION,
    CONF_LOCATION_MODE,
    DOMAIN,
    LOCATION_MODE_CUSTOM,
    LOCATION_MODE_HASS,
    LOCATION_MODE_STATION,
)


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    # Submit only the station: Name and location mode fall back to their
    # defaults (HA location name, "same as station") — preserving the old
    # single-field behaviour for anyone who just picks a station.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_IND_KLI: "11858"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # Title is now the (defaulted) Name, not the station name.
    assert result["title"] == hass.config.location_name
    assert result["data"] == {
        CONF_IND_KLI: 11858,
        CONF_NAME: hass.config.location_name,
    }
    assert result["options"] == {CONF_LOCATION_MODE: LOCATION_MODE_STATION}


async def test_user_flow_explicit_name(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_IND_KLI: "11858",
            CONF_NAME: "Cottage",
            CONF_LOCATION_MODE: LOCATION_MODE_STATION,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cottage"
    assert result["data"][CONF_NAME] == "Cottage"


async def test_user_flow_blank_name_falls_back_to_station(
    hass: HomeAssistant,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_IND_KLI: "11858",
            CONF_NAME: "   ",  # whitespace-only — must not become the name
            CONF_LOCATION_MODE: LOCATION_MODE_STATION,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hurbanovo"
    assert result["data"][CONF_NAME] == "Hurbanovo"


async def test_user_flow_home_location(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_IND_KLI: "11858",
            CONF_NAME: "Home",
            CONF_LOCATION_MODE: LOCATION_MODE_HASS,
        },
    )
    # Home mode is a single step — no map.
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {CONF_LOCATION_MODE: LOCATION_MODE_HASS}


async def test_user_flow_custom_location_second_step(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_IND_KLI: "11858",
            CONF_NAME: "Field",
            CONF_LOCATION_MODE: LOCATION_MODE_CUSTOM,
        },
    )
    # Custom mode opens the map picker as a second step.
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "custom"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_LOCATION: {CONF_LATITUDE: 48.15, CONF_LONGITUDE: 17.11}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        CONF_LOCATION_MODE: LOCATION_MODE_CUSTOM,
        CONF_LOCATION: {CONF_LATITUDE: 48.15, CONF_LONGITUDE: 17.11},
    }


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


async def test_options_flow_switches_to_home(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="11858",
        title="Home",
        data={CONF_IND_KLI: 11858, CONF_NAME: "Home"},
        options={CONF_LOCATION_MODE: LOCATION_MODE_STATION},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCATION_MODE: LOCATION_MODE_HASS}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_LOCATION_MODE: LOCATION_MODE_HASS}


async def test_options_flow_custom_location_second_step(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="11858",
        title="Home",
        data={CONF_IND_KLI: 11858, CONF_NAME: "Home"},
        options={CONF_LOCATION_MODE: LOCATION_MODE_STATION},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCATION_MODE: LOCATION_MODE_CUSTOM}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "custom"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_LOCATION: {CONF_LATITUDE: 49.0, CONF_LONGITUDE: 20.0}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_LOCATION_MODE: LOCATION_MODE_CUSTOM,
        CONF_LOCATION: {CONF_LATITUDE: 49.0, CONF_LONGITUDE: 20.0},
    }
