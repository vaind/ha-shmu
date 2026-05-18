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
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_IND_KLI,
    DOMAIN,
    OBSERVATION_STALE_AFTER,
    POLL_INTERVAL_MINUTES,
    POLL_OFFSET_MAX_SECONDS,
    POLL_OFFSET_MIN_SECONDS,
    POLL_OFFSET_PAD_SECONDS,
)
from .shmu_opendata import (
    ForecastSnapshot,
    Observation,
    ObservationSnapshot,
    RadarFrame,
    RadarSnapshot,
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


def _next_grid_time(now: datetime, interval_minutes: int) -> datetime:
    """Return the next UTC time strictly after ``now`` on the N-minute grid."""
    floor = now.replace(
        minute=now.minute - now.minute % interval_minutes,
        second=0,
        microsecond=0,
    )
    return floor + timedelta(minutes=interval_minutes)


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
    forecast: ForecastSnapshot | None
    radar: RadarSnapshot | None

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

    def resolve_condition(
        self, station: Station, observation: Observation | None
    ) -> tuple[str | None, str]:
        """Resolve a station's HA condition and which source produced it.

        Single source of truth for the website -> ``stav_poc`` -> unknown
        precedence, shared by the weather entity and diagnostics so they
        cannot drift. ``observation`` is supplied by the caller (the
        coordinator's carried-forward reading) so the fallback survives a
        one-cycle station dropout. ``source`` is ``"website"``, ``"stav_poc"``
        or ``"unknown"``; the day/night ``sunny`` -> ``clear-night`` shift is
        a UI concern and stays in the weather entity.
        """
        if self.web_conditions is not None:
            web = self.web_conditions.conditions.get(station.ind_kli)
            if web is not None and web.condition is not None:
                return web.condition, "website"

        if observation is not None:
            derived = condition_from_weather_code(
                observation.weather_code, precipitation=observation.precipitation
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
        """Initialise the coordinator.

        ``update_interval`` is left unset: polling is driven on the upstream
        UTC 5-minute grid by ``async_setup_entry`` instead of a fixed period,
        so we fetch each snapshot just after it is published rather than
        drifting behind it.
        """
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
        )
        self._client = client
        station = get_station(config_entry.data[CONF_IND_KLI])
        assert station is not None  # value comes from the fixed station list
        #: The configured station; platforms read this instead of re-resolving.
        self.station: Station = station
        #: Tracks station-presence so we log only on transitions, not every poll.
        self._station_present = True
        #: Last reading we saw for the station and when we obtained it; served
        #: across one-cycle dropouts so entities don't flicker (see
        #: `observation`). Freshness is measured from acquisition time, not the
        #: reading's upstream timestamp.
        self._last_observation: Observation | None = None
        self._last_observation_at: datetime | None = None
        #: Recently observed publish lags (s) for offset auto-tuning.
        self._recent_lags: deque[float] = deque(maxlen=5)
        #: Update health, surfaced in diagnostics.
        self._last_success_at: datetime | None = None
        self._failures_since_success = 0
        #: Grid scheduling state.
        self._next_refresh_at: datetime | None = None
        self._unsub_refresh: CALLBACK_TYPE | None = None
        #: UI scrub position for the radar loop: how many 5-minute frames back
        #: from the newest one to show (0 = live). Set by the "Radar frame"
        #: number entity, read by the selectable-frame image; runtime-only,
        #: roll-stable (0 always = the latest frame as the buffer rotates).
        self.radar_frame_offset: int = 0

    @property
    def observation(self) -> Observation | None:
        """The station's reading, carried forward across one-cycle dropouts.

        Returns the last reading we saw, or ``None`` once it is older than
        ``OBSERVATION_STALE_AFTER`` (a genuine outage, not a transient gap).
        """
        obs = self._last_observation
        if obs is None or self._last_observation_at is None:
            return None
        if dt_util.utcnow() - self._last_observation_at > OBSERVATION_STALE_AFTER:
            return None
        return obs

    @property
    def last_success_at(self) -> datetime | None:
        """When the last fully-successful update completed (UTC)."""
        return self._last_success_at

    @property
    def failures_since_success(self) -> int:
        """Consecutive failed updates since the last successful one."""
        return self._failures_since_success

    @property
    def next_refresh_at(self) -> datetime | None:
        """When the next grid-aligned refresh is scheduled (UTC)."""
        return self._next_refresh_at

    def selected_radar_frame(self) -> RadarFrame | None:
        """The buffered radar frame the UI scrubber points at.

        Resolves :attr:`radar_frame_offset` against the current loop buffer,
        clamped so it stays valid as the buffer grows/rotates. ``None`` when
        no radar is held. Shared by the "Radar frame" number and the
        selectable-frame image so they never disagree on which frame is
        shown.
        """
        radar = self.data.radar if self.data else None
        if radar is None or not radar.frames:
            return None
        offset = max(0, min(self.radar_frame_offset, len(radar.frames) - 1))
        return radar.frames[-1 - offset]

    def _offset_seconds(self) -> int:
        """Auto-tuned delay after the grid boundary.

        Tracks the worst recent publish lag (so we don't fetch the previous
        file) plus a fixed safety pad, clamped to a sane range.
        """
        lag = max(self._recent_lags) if self._recent_lags else 0.0
        return int(
            min(
                max(lag + POLL_OFFSET_PAD_SECONDS, POLL_OFFSET_MIN_SECONDS),
                POLL_OFFSET_MAX_SECONDS,
            )
        )

    @callback
    def async_schedule_refresh(self) -> None:
        """(Re)arm the one-shot timer for the next grid boundary + offset."""
        if self._unsub_refresh is not None:
            self._unsub_refresh()
        now = dt_util.utcnow()
        target = _next_grid_time(now, POLL_INTERVAL_MINUTES) + timedelta(
            seconds=self._offset_seconds()
        )
        self._next_refresh_at = target
        self._unsub_refresh = async_track_point_in_utc_time(
            self.hass, self._handle_scheduled_refresh, target
        )

    @callback
    def async_cancel_refresh(self) -> None:
        """Cancel the pending grid timer (called on unload)."""
        if self._unsub_refresh is not None:
            self._unsub_refresh()
            self._unsub_refresh = None

    async def _handle_scheduled_refresh(self, _now: datetime) -> None:
        self._unsub_refresh = None
        try:
            await self.async_request_refresh()
        finally:
            # Always keep polling, even if this cycle failed.
            self.async_schedule_refresh()

    def _record_publish_lag(self, snapshot: ObservationSnapshot) -> None:
        """Feed the offset auto-tuner from the file's Last-Modified time."""
        published = snapshot.published_at
        if published is None:
            return
        grid = published.replace(
            minute=published.minute - published.minute % POLL_INTERVAL_MINUTES,
            second=0,
            microsecond=0,
        )
        lag = (published - grid).total_seconds()
        if 0 <= lag < POLL_INTERVAL_MINUTES * 60:
            self._recent_lags.append(lag)

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
        try:
            data = await self._fetch()
        except Exception:
            self._failures_since_success += 1
            raise

        self._last_success_at = dt_util.utcnow()
        self._failures_since_success = 0
        self._record_publish_lag(data.observations)
        obs = data.observations.observations.get(self.station.ind_kli)
        if obs is not None:
            self._last_observation = obs
            self._last_observation_at = self._last_success_at
        self._log_station_presence(data)
        return data

    async def _fetch(self) -> ShmuData:
        previous = self.data

        observations_coro = self._client.async_get_observations(
            previous=previous.observations if previous else None
        )
        warnings_coro = self._client.async_get_warnings(
            previous=previous.warnings if previous else None
        )
        web_coro = self._client.async_get_web_conditions()
        # Forecast discovery is cheap (small directory listings); the large
        # GRIB2 set is re-downloaded only when the model run folder changes
        # (~4x/day), so running this every observation cycle does not increase
        # the heavy request rate — same identity-cache idea as observations.
        forecast_coro = self._client.async_get_forecast(
            self.station.latitude,
            self.station.longitude,
            previous=previous.forecast if previous else None,
        )
        # Radar discovery is a small listing too; the ~0.3 MB ODIM frame is
        # re-fetched only when a new composite is published (its path is the
        # cache key) — same identity-cache idea as observations.
        radar_coro = self._client.async_get_radar(
            self.station.latitude,
            self.station.longitude,
            previous=previous.radar if previous else None,
            tz=self.hass.config.time_zone,
        )

        observations, warnings, web, forecast, radar = await asyncio.gather(
            observations_coro,
            warnings_coro,
            web_coro,
            forecast_coro,
            radar_coro,
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
        forecast = _keep_previous(
            forecast, "forecast", previous.forecast if previous else None
        )
        radar = _keep_previous(radar, "radar", previous.radar if previous else None)

        return ShmuData(
            observations=observations,
            warnings=warnings,
            web_conditions=web,
            forecast=forecast,
            radar=radar,
        )
