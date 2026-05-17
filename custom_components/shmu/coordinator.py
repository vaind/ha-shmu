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
    get_station,
)

_LOGGER = logging.getLogger(__name__)


def _keep_previous[T](
    result: T | BaseException, label: str, fallback: T | None
) -> T | None:
    """Resolve a supplementary fetch result for the coordinator.

    Returns ``result`` on success, or ``fallback`` (the last good value) if it
    failed with an ordinary ``Exception``. A non-``Exception`` ``BaseException``
    — ``CancelledError`` from a gather() on shutdown/reload — is re-raised so
    cooperative cancellation is never swallowed.
    """
    if isinstance(result, BaseException):
        if not isinstance(result, Exception):
            raise result
        _LOGGER.warning("SHMÚ %s unavailable, keeping previous: %s", label, result)
        return fallback
    return result


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
        station = get_station(config_entry.data[CONF_IND_KLI])
        assert station is not None  # value comes from the fixed station list
        #: The configured station; platforms read this instead of re-resolving.
        self.station: Station = station
        #: Tracks station-presence so we log only on transitions, not every poll.
        self._station_present = True

    def _log_station_presence(self, data: ShmuData) -> None:
        """Log (once per transition) whether the chosen station is reporting.

        A synoptic station can drop out of a 5-minute snapshot; its entities
        then go unavailable. Without this an operator has no idea why.
        """
        ind_kli = self.station.ind_kli
        present = ind_kli in data.observations.observations
        if present and not self._station_present:
            _LOGGER.info("SHMÚ station %s is reporting again", ind_kli)
        elif not present and self._station_present:
            _LOGGER.info(
                "SHMÚ station %s is not in the latest observation snapshot "
                "(%s); its entities will be unavailable until it reports again",
                ind_kli,
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

        # Warnings & website conditions are supplementary — keep the last good
        # value on an ordinary failure instead of blanking every entity.
        warnings = _keep_previous(
            warnings, "warnings", previous.warnings if previous else None
        )
        web = _keep_previous(
            web, "website conditions", previous.web_conditions if previous else None
        )

        data = ShmuData(
            observations=observations,
            warnings=warnings,
            web_conditions=web,
        )
        self._log_station_presence(data)
        return data
