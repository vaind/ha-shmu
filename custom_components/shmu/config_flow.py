"""Config and options flows for the SHMÚ Weather integration.

The observation station (``ind_kli``) is chosen once at setup and is the
device identity, so it lives in ``entry.data`` and is not editable afterwards
(add the integration again to track another station). The *measurement
location* — the point used for the forecast, radar crop and warning relevance —
is decoupled from the station and lives in ``entry.options`` so it can be
changed later via the options flow without re-adding the integration.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    LocationSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_IND_KLI,
    CONF_LOCATION,
    CONF_LOCATION_MODE,
    DEFAULT_LOCATION_MODE,
    DOMAIN,
    LOCATION_MODE_CUSTOM,
    LOCATION_MODES,
)
from .shmu_opendata import STATIONS, get_station, nearest_station

_STATION_OPTIONS = [
    SelectOptionDict(value=str(station.ind_kli), label=station.name)
    for station in sorted(STATIONS, key=lambda s: s.name)
]


def _mode_selector(default: str) -> dict[Any, Any]:
    """A schema fragment for the location-mode picker, shared by both flows.

    The option labels come from ``selector.location_mode.options.*`` in the
    translations (via ``translation_key``), so the config and options flows
    present identical wording without duplicating strings.
    """
    return {
        vol.Required(CONF_LOCATION_MODE, default=default): SelectSelector(
            SelectSelectorConfig(
                options=list(LOCATION_MODES),
                mode=SelectSelectorMode.LIST,
                translation_key="location_mode",
            )
        )
    }


def _custom_location_schema(latitude: float, longitude: float) -> vol.Schema:
    """A one-field schema for the custom-point map, defaulted to ``lat/lon``."""
    return vol.Schema(
        {
            vol.Required(
                CONF_LOCATION,
                default={CONF_LATITUDE: latitude, CONF_LONGITUDE: longitude},
            ): LocationSelector()
        }
    )


def _custom_location_options(location: dict[str, Any]) -> dict[str, Any]:
    """Build the options dict for the custom mode from a selector value.

    :class:`LocationSelector` yields ``{"latitude", "longitude", "radius"}``;
    only the coordinates are meaningful here, so the radius is dropped.
    """
    return {
        CONF_LOCATION_MODE: LOCATION_MODE_CUSTOM,
        CONF_LOCATION: {
            CONF_LATITUDE: location[CONF_LATITUDE],
            CONF_LONGITUDE: location[CONF_LONGITUDE],
        },
    }


class ShmuConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial SHMÚ Weather configuration flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Hold the first step's answers while the custom step is shown."""
        self._ind_kli: int | None = None
        self._name: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the station, a name, and how to choose the measurement location."""
        if user_input is not None:
            ind_kli = int(user_input[CONF_IND_KLI])
            await self.async_set_unique_id(str(ind_kli))
            self._abort_if_unique_id_configured()
            station = get_station(ind_kli)
            assert station is not None  # value comes from the fixed station list
            self._ind_kli = ind_kli
            # The field is pre-filled but can be cleared; fall back to the
            # station name so the device is never left unnamed.
            self._name = user_input[CONF_NAME].strip() or station.name
            mode = user_input[CONF_LOCATION_MODE]
            if mode == LOCATION_MODE_CUSTOM:
                return await self.async_step_custom()
            return self._create_entry({CONF_LOCATION_MODE: mode})

        default = nearest_station(self.hass.config.latitude, self.hass.config.longitude)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_IND_KLI, default=str(default.ind_kli)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=_STATION_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_NAME, default=self.hass.config.location_name): str,
                **_mode_selector(DEFAULT_LOCATION_MODE),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user drop a pin for a custom measurement location."""
        if user_input is not None:
            return self._create_entry(
                _custom_location_options(user_input[CONF_LOCATION])
            )
        return self.async_show_form(
            step_id="custom",
            data_schema=_custom_location_schema(
                self.hass.config.latitude, self.hass.config.longitude
            ),
        )

    def _create_entry(self, options: dict[str, Any]) -> ConfigFlowResult:
        """Create the entry from the gathered station, name and location.

        ``_ind_kli`` and ``_name`` are resolved (and the station validated) in
        :meth:`async_step_user` before either path reaches here.
        """
        assert self._ind_kli is not None
        assert self._name is not None
        return self.async_create_entry(
            title=self._name,
            data={CONF_IND_KLI: self._ind_kli, CONF_NAME: self._name},
            options=options,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> ShmuOptionsFlow:
        """Return the options flow for changing the measurement location."""
        return ShmuOptionsFlow()


class ShmuOptionsFlow(OptionsFlow):
    """Change the measurement location after setup (station stays fixed)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the location mode; branch to the map for a custom point."""
        if user_input is not None:
            mode = user_input[CONF_LOCATION_MODE]
            if mode == LOCATION_MODE_CUSTOM:
                return await self.async_step_custom()
            return self.async_create_entry(data={CONF_LOCATION_MODE: mode})

        current = self.config_entry.options.get(
            CONF_LOCATION_MODE, DEFAULT_LOCATION_MODE
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(_mode_selector(current)),
        )

    async def async_step_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user drop a pin, prefilled with the current/home point."""
        if user_input is not None:
            return self.async_create_entry(
                data=_custom_location_options(user_input[CONF_LOCATION])
            )

        previous = self.config_entry.options.get(CONF_LOCATION, {})
        latitude = previous.get(CONF_LATITUDE, self.hass.config.latitude)
        longitude = previous.get(CONF_LONGITUDE, self.hass.config.longitude)
        return self.async_show_form(
            step_id="custom",
            data_schema=_custom_location_schema(latitude, longitude),
        )
