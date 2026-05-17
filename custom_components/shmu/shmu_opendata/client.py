"""Async client for the SHMÚ open-data file server.

The server is a static Apache index with no API, so each request first reads a
small directory listing to discover the newest file. Bodies are only the
~350 KB observation snapshot or the small CAP XML set.

SHMÚ logs client IPs for abuse protection and the exact rate limit is
undocumented, so the client is deliberately polite: pass the previous snapshot
back in and, when the newest file has not changed, the large body is **not**
re-downloaded — only the tiny listing is read.
"""

from __future__ import annotations

import logging
import re
import ssl
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import aiohttp

from .const import (
    BASE_URL,
    DEFAULT_TIMEOUT,
    FORECAST_HOURS,
    FORECAST_PATH,
    OBSERVATIONS_PATH,
    USER_AGENT,
    WARNINGS_PATH,
)
from .exceptions import ShmuConnectionError, ShmuDataError
from .forecast import ForecastStep, grid_index, parse_forecast
from .models import Observation, Warning
from .parsers import list_directory, parse_cap_alert, parse_observations
from .website import WEBSITE_URL, WebCondition, parse_current_conditions

_LOGGER = logging.getLogger(__name__)

_DAY_DIR_RE = re.compile(r"^\d{8}/$")
_ISSUANCE_DIR_RE = re.compile(r"^\d{4}/$")
_OBS_FILE_RE = re.compile(r"^aws1min .*\.json$")
_CAP_FILE_RE = re.compile(r"^[^/]+\.cap\.xml$")
_FCAST_FILE_RE = re.compile(r"^al-grib_sk_(\d{3})-(\d{8})-(\d{4})-nwp-\.grb$")


@dataclass(frozen=True, slots=True)
class ObservationSnapshot:
    """Latest observations plus the source file they were parsed from.

    ``published_at`` is the file's server ``Last-Modified`` time (UTC), used
    by the coordinator to auto-tune how long after the 5-minute grid boundary
    it should poll. ``None`` if the server omitted/garbled the header.
    """

    observations: dict[int, Observation]
    source: str
    fetched_at: datetime
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class WarningsSnapshot:
    """All warnings from the latest CAP issuance, plus its source folder."""

    warnings: list[Warning]
    source: str
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class WebConditionsSnapshot:
    """Per-station qualitative conditions scraped from the SHMÚ website.

    This is the supplementary, swappable condition source (see
    :mod:`shmu_opendata.website`); numeric data never comes from here.
    """

    conditions: dict[int, WebCondition]
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class ForecastSnapshot:
    """An ALADIN model run decoded at the configured location.

    ``run`` is the model reference time (UTC); ``source`` is the run folder
    path and doubles as the cache identity — a run never changes once
    complete, so an unchanged ``source`` means the (large) GRIB2 set need not
    be re-downloaded until SHMÚ publishes the next run. ``grid_point`` is the
    projected ALADIN cell ``(i, j)`` for the location, surfaced for
    diagnostics provenance.
    """

    steps: list[ForecastStep]
    run: datetime
    source: str
    grid_point: tuple[int, int]
    fetched_at: datetime


class ShmuClient:
    """Reads observations and weather warnings from opendata.shmu.sk."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        ssl_context: ssl.SSLContext | None = None,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Create a client.

        ``ssl_context`` (see :func:`shmu_opendata.create_ssl_context`) is
        applied per request, so a shared/default ``session`` can be reused
        without giving it a custom connector. SHMÚ omits a TLS intermediate,
        so without it requests fail verification.
        """
        self._session = session
        # aiohttp's ssl= default is True (normal verification); fall back to
        # that when no custom context is supplied.
        self._ssl: ssl.SSLContext | bool = (
            ssl_context if ssl_context is not None else True
        )
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _request(self, url: str) -> tuple[bytes, datetime | None]:
        """Fetch ``url``; return its body and parsed ``Last-Modified`` (UTC)."""
        try:
            async with self._session.get(
                url,
                timeout=self._timeout,
                headers={"User-Agent": USER_AGENT},
                ssl=self._ssl,
            ) as response:
                response.raise_for_status()
                body = await response.read()
                last_modified = response.headers.get("Last-Modified")
        except aiohttp.ClientError as err:
            raise ShmuConnectionError(f"Failed to fetch {url}: {err}") from err
        except TimeoutError as err:
            raise ShmuConnectionError(f"Timed out fetching {url}") from err

        published_at: datetime | None = None
        if last_modified:
            try:
                published_at = parsedate_to_datetime(last_modified).astimezone(UTC)
            except (TypeError, ValueError):
                published_at = None
        return body, published_at

    async def _get_url(self, url: str) -> bytes:
        body, _ = await self._request(url)
        return body

    async def _get(self, path: str) -> bytes:
        return await self._get_url(f"{self._base_url}{path}")

    async def _list(self, path: str) -> list[str]:
        html = (await self._get(f"{path}/")).decode("iso-8859-1")
        return list_directory(html)

    async def _latest_entry(self, path: str, pattern: re.Pattern[str]) -> str:
        """Return the lexicographically newest matching entry under ``path``.

        SHMÚ names day folders ``YYYYMMDD/``, issuance folders ``HHMM/`` and
        snapshot files with an embedded ISO timestamp, so lexical max == newest.
        """
        entries = [e for e in await self._list(path) if pattern.match(e)]
        if not entries:
            raise ShmuDataError(f"No entries matching {pattern.pattern!r} in {path}")
        return max(entries)

    async def _latest_observation_file(self) -> tuple[str, str]:
        """Return ``(day_path, filename)`` of the newest observation snapshot.

        Walks day folders newest-first and returns the first that actually
        contains a snapshot. SHMÚ creates the new ``YYYYMMDD/`` folder around
        00:00 UTC slightly before the day's first 5-minute file lands; without
        this fallback that gap would raise ``ShmuDataError`` once a day.
        """
        days = sorted(
            (e for e in await self._list(OBSERVATIONS_PATH) if _DAY_DIR_RE.match(e)),
            reverse=True,
        )
        if not days:
            raise ShmuDataError(f"No day folders in {OBSERVATIONS_PATH}")
        # Two folders is enough to bridge a midnight rollover; scanning more
        # would just mask a genuinely stalled feed.
        for day in days[:2]:
            day_path = f"{OBSERVATIONS_PATH}/{day.rstrip('/')}"
            files = [e for e in await self._list(day_path) if _OBS_FILE_RE.match(e)]
            if files:
                return day_path, max(files)
        raise ShmuDataError(
            f"No observation files in the {len(days[:2])} newest day folders "
            f"under {OBSERVATIONS_PATH}"
        )

    async def async_get_observations(
        self, previous: ObservationSnapshot | None = None
    ) -> ObservationSnapshot:
        """Fetch the latest observation snapshot.

        If the newest snapshot file is the same one ``previous`` was parsed
        from, the large body is not re-downloaded and ``previous`` is returned.
        """
        day_path, filename = await self._latest_observation_file()
        source = f"{day_path}/{filename}"

        if previous is not None and previous.source == source:
            _LOGGER.debug("Observations unchanged (%s); using cache", source)
            return previous

        payload, published_at = await self._request(
            f"{self._base_url}{day_path}/{quote(filename)}"
        )
        observations = parse_observations(payload)
        _LOGGER.debug("Parsed %d stations from %s", len(observations), source)
        return ObservationSnapshot(
            observations=observations,
            source=source,
            fetched_at=datetime.now(UTC),
            published_at=published_at,
        )

    async def async_get_warnings(
        self, previous: WarningsSnapshot | None = None
    ) -> WarningsSnapshot:
        """Fetch all warnings from the latest CAP issuance.

        Returns every parsed alert (no time/area filtering); callers decide
        what is active and relevant. If the newest issuance folder is unchanged
        from ``previous``, the XML set is not re-downloaded.

        **Verified invariant (2026-05-17):** each ``HHMM/`` issuance folder
        republishes the *complete* set of currently-active alerts, not deltas
        — including multi-day warnings that originated on earlier days. So
        reading only the newest issuance of the newest day is sufficient. If
        SHMÚ ever switches to incremental issuances, still-active earlier
        alerts would wrongly disappear; the fix would then be to union recent
        issuances within the active window. Re-check with the script in
        CLAUDE.md if warnings behave oddly.
        """
        day = await self._latest_entry(WARNINGS_PATH, _DAY_DIR_RE)
        day_path = f"{WARNINGS_PATH}/{day.rstrip('/')}"
        issuance = await self._latest_entry(day_path, _ISSUANCE_DIR_RE)
        issuance_path = f"{day_path}/{issuance.rstrip('/')}"

        if previous is not None and previous.source == issuance_path:
            _LOGGER.debug("Warnings unchanged (%s); using cache", issuance_path)
            return previous

        files = [e for e in await self._list(issuance_path) if _CAP_FILE_RE.match(e)]
        warnings: list[Warning] = []
        for name in sorted(files):
            payload = await self._get(f"{issuance_path}/{quote(name)}")
            try:
                warnings.append(parse_cap_alert(payload))
            except ShmuDataError as err:
                # One malformed alert must not sink the whole batch.
                _LOGGER.warning("Skipping unparseable CAP file %s: %s", name, err)
        _LOGGER.debug("Parsed %d warnings from %s", len(warnings), issuance_path)
        return WarningsSnapshot(
            warnings=warnings,
            source=issuance_path,
            fetched_at=datetime.now(UTC),
        )

    async def async_get_web_conditions(self) -> WebConditionsSnapshot:
        """Scrape per-station qualitative conditions from the SHMÚ website.

        Supplements the open-data feed, which lacks cloud cover. The page is
        small (~90 KB) and dynamic with no stable per-file identity, so it is
        fetched fresh each call; politeness comes from the caller's poll cadence.
        """
        html = (await self._get_url(WEBSITE_URL)).decode("utf-8", "replace")
        conditions = parse_current_conditions(html)
        _LOGGER.debug("Parsed website conditions for %d stations", len(conditions))
        return WebConditionsSnapshot(
            conditions=conditions,
            fetched_at=datetime.now(UTC),
        )

    async def async_get_forecast(
        self,
        latitude: float,
        longitude: float,
        *,
        forecast_hours: Sequence[int] = FORECAST_HOURS,
        previous: ForecastSnapshot | None = None,
    ) -> ForecastSnapshot:
        """Decode the newest *complete* ALADIN run at a location.

        Run discovery mirrors the observation pattern: only small directory
        listings are read each call; the large GRIB2 set is fetched solely
        when the chosen run folder differs from ``previous``. A run is
        immutable once complete, so its folder path is a stable cache key.
        Only a run whose last requested hour is published is used — until
        then ``previous`` keeps serving, so a half-published run never
        truncates the forecast. Newest two days are scanned to bridge a
        midnight rollover (same rationale as the observation walk).
        """
        wanted = sorted(set(forecast_hours))
        if not wanted:
            raise ShmuDataError("No forecast hours requested")
        target_hour = wanted[-1]

        days = sorted(
            (e for e in await self._list(FORECAST_PATH) if _DAY_DIR_RE.match(e)),
            reverse=True,
        )
        for day in days[:2]:
            day_dir = day.rstrip("/")
            day_path = f"{FORECAST_PATH}/{day_dir}"
            runs = sorted(
                (e for e in await self._list(day_path) if _ISSUANCE_DIR_RE.match(e)),
                reverse=True,
            )
            for run in runs:
                run_dir = run.rstrip("/")
                run_path = f"{day_path}/{run_dir}"
                available: dict[int, str] = {}
                for entry in await self._list(run_path):
                    match = _FCAST_FILE_RE.match(entry)
                    if match is not None:
                        available[int(match.group(1))] = entry
                if target_hour not in available:
                    continue  # run still publishing; fall back to an older one

                if previous is not None and previous.source == run_path:
                    _LOGGER.debug("Forecast run unchanged (%s); using cache", run_path)
                    return previous

                pairs: list[tuple[int, bytes]] = []
                for hour in wanted:
                    name = available.get(hour)
                    if name is None:
                        continue
                    payload = await self._get(f"{run_path}/{quote(name)}")
                    pairs.append((hour, payload))

                run_dt = datetime.strptime(f"{day_dir}{run_dir}", "%Y%m%d%H%M").replace(
                    tzinfo=UTC
                )
                _LOGGER.debug("Decoded %d forecast hours from %s", len(pairs), run_path)
                return ForecastSnapshot(
                    steps=parse_forecast(pairs, latitude, longitude),
                    run=run_dt,
                    source=run_path,
                    grid_point=grid_index(latitude, longitude),
                    fetched_at=datetime.now(UTC),
                )
        raise ShmuDataError(
            f"No complete ALADIN run (needs hour {target_hour:03d}) "
            f"under {FORECAST_PATH}"
        )
