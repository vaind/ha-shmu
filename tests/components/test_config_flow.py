"""Config- and options-flow tests."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.config_flow import SYNOPTIC_MARK
from custom_components.shmu.const import (
    CONF_IND_KLI,
    CONF_LOCATION,
    CONF_LOCATION_MODE,
    DOMAIN,
    LOCATION_MODE_CUSTOM,
    LOCATION_MODE_HASS,
    LOCATION_MODE_STATION,
)
from custom_components.shmu.shmu_opendata import STATIONS


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


@pytest.mark.parametrize(
    ("latitude", "longitude", "expected"),
    [
        # Right by Hurbanovo, a synoptic station.
        (47.8733, 18.1944, "11858"),
        # Banská Bystrica: its station is not synoptic, and the nearest
        # synoptic one (Sliač) is ~10 km away — the full list must be used.
        (48.7350, 19.1150, "11898"),
    ],
)
async def test_user_flow_defaults_to_nearest_station(
    hass: HomeAssistant, latitude: float, longitude: float, expected: str
) -> None:
    hass.config.latitude = latitude
    hass.config.longitude = longitude

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    schema = result["data_schema"].schema
    key = next(iter(schema))
    assert key.default() == expected


async def test_user_flow_lists_every_station_marking_synoptic(
    hass: HomeAssistant,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    selector = next(iter(result["data_schema"].schema.values()))
    labels = {o["value"]: o["label"] for o in selector.config["options"]}
    assert len(labels) == len(STATIONS)
    assert labels["11858"] == f"Hurbanovo {SYNOPTIC_MARK}"
    assert labels["11898"] == "Banská Bystrica"


async def test_automatic_station_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_IND_KLI: "11898", CONF_NAME: ""}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # A cleared Name falls back to the station name, as for synoptic ones.
    assert result["title"] == "Banská Bystrica"
    assert result["data"][CONF_IND_KLI] == 11898


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
