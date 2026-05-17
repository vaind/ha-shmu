"""Single shared coordinator for all SHMÚ data.

One coordinator feeds the weather, sensor and binary_sensor platforms so the
upstream server is hit once per cycle regardless of how many entities exist.
Observations are the critical dataset; the supplementary website conditions
and the CAP warnings degrade gracefully (last good value is kept) rather than
making every entity unavailable when only one source hiccups.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_IND_KLI, DOMAIN, UPDATE_INTERVAL
from .shmu_opendata import (
    ObservationSnapshot,
    ShmuClient,
    ShmuConnectionError,
    ShmuDataError,
    Station,
    Warning,
    WarningsSnapshot,
    WebConditionsSnapshot,
    condition_from_weather_code,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ShmuData:
    """Latest snapshots from every SHMÚ source."""

    observations: ObservationSnapshot
    warnings: WarningsSnapshot | None
    web_conditions: WebConditionsSnapshot | None

    def active_warnings_for(self, station: Station) -> list[Warning]:
        """Active warnings whose area covers the station, worst severity first."""
        if self.warnings is None:
            return []
        now = dt_util.utcnow()
        relevant = [
            w
            for w in self.warnings.warnings
            if w.is_active(now) and w.covers(station.latitude, station.longitude)
        ]
        relevant.sort(key=lambda w: _SEVERITY_ORDER.get(w.severity, 0), reverse=True)
        return relevant

    def resolve_condition(self, station: Station) -> tuple[str | None, str]:
        """Resolve a station's HA condition and which source produced it.

        Single source of truth for the website -> ``stav_poc`` -> unknown
        precedence, shared by the weather entity and diagnostics so they
        cannot drift. ``source`` is ``"website"``, ``"stav_poc"`` or
        ``"unknown"``. The day/night ``sunny`` -> ``clear-night`` shift is a
        UI concern and stays in the weather entity.
        """
        if self.web_conditions is not None:
            web = self.web_conditions.conditions.get(station.ind_kli)
            if web is not None and web.condition is not None:
                return web.condition, "website"

        obs = self.observations.observations.get(station.ind_kli)
        if obs is not None:
            derived = condition_from_weather_code(
                obs.weather_code, precipitation=obs.precipitation
            )
            if derived is not None:
                return derived, "stav_poc"

        return None, "unknown"


#: CAP severity ranked for "worst first" ordering / a sensor state.
_SEVERITY_ORDER = {
    "Minor": 1,
    "Moderate": 2,
    "Severe": 3,
    "Extreme": 4,
}


type ShmuConfigEntry = ConfigEntry[ShmuDataUpdateCoordinator]


class ShmuDataUpdateCoordinator(DataUpdateCoordinator[ShmuData]):
    """Fetches observations, website conditions and warnings together."""

    config_entry: ShmuConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ShmuConfigEntry,
        client: ShmuClient,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._client = client
        self._ind_kli: int = config_entry.data[CONF_IND_KLI]
        #: Tracks station-presence so we log only on transitions, not every poll.
        self._station_present = True

    def _log_station_presence(self, data: ShmuData) -> None:
        """Log (once per transition) whether the chosen station is reporting.

        A synoptic station can drop out of a 5-minute snapshot; its entities
        then go unavailable. Without this an operator has no idea why.
        """
        present = self._ind_kli in data.observations.observations
        if present and not self._station_present:
            _LOGGER.info("SHMÚ station %s is reporting again", self._ind_kli)
        elif not present and self._station_present:
            _LOGGER.info(
                "SHMÚ station %s is not in the latest observation snapshot "
                "(%s); its entities will be unavailable until it reports again",
                self._ind_kli,
                data.observations.source,
            )
        self._station_present = present

    async def _async_update_data(self) -> ShmuData:
        previous = self.data

        observations_coro = self._client.async_get_observations(
            previous=previous.observations if previous else None
        )
        warnings_coro = self._client.async_get_warnings(
            previous=previous.warnings if previous else None
        )
        web_coro = self._client.async_get_web_conditions()

        observations, warnings, web = await asyncio.gather(
            observations_coro,
            warnings_coro,
            web_coro,
            return_exceptions=True,
        )

        # Observations are mandatory: without them the integration has no data.
        if isinstance(observations, BaseException):
            if isinstance(observations, ShmuConnectionError | ShmuDataError):
                raise UpdateFailed(
                    f"Could not fetch SHMÚ observations: {observations}"
                ) from observations
            raise observations

        # Warnings & website conditions are supplementary — keep last good
        # value on failure instead of blanking every entity. But never swallow
        # cancellation/shutdown: gather() returns CancelledError as a result,
        # so re-raise anything that isn't an ordinary Exception.
        if isinstance(warnings, BaseException):
            if not isinstance(warnings, Exception):
                raise warnings
            _LOGGER.warning("SHMÚ warnings unavailable, keeping previous: %s", warnings)
            warnings = previous.warnings if previous else None
        if isinstance(web, BaseException):
            if not isinstance(web, Exception):
                raise web
            _LOGGER.warning(
                "SHMÚ website conditions unavailable, keeping previous: %s", web
            )
            web = previous.web_conditions if previous else None

        data = ShmuData(
            observations=observations,
            warnings=warnings,
            web_conditions=web,
        )
        self._log_station_presence(data)
        return data
