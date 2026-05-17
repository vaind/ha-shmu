"""Config flow for the SHMÚ Weather integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_IND_KLI, DOMAIN
from .shmu_opendata import STATIONS, get_station, nearest_station

_STATION_OPTIONS = [
    SelectOptionDict(value=str(station.ind_kli), label=station.name)
    for station in sorted(STATIONS, key=lambda s: s.name)
]


class ShmuConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the SHMÚ Weather configuration flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a station (defaulting to the nearest one)."""
        if user_input is not None:
            ind_kli = int(user_input[CONF_IND_KLI])
            await self.async_set_unique_id(str(ind_kli))
            self._abort_if_unique_id_configured()
            station = get_station(ind_kli)
            assert station is not None  # value comes from the fixed station list
            return self.async_create_entry(
                title=station.name, data={CONF_IND_KLI: ind_kli}
            )

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
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
