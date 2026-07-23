"""Weather forecast tests (ALADIN model via the stubbed client)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.components.weather import WeatherEntityFeature
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import CONF_IND_KLI, DOMAIN
from custom_components.shmu.diagnostics import async_get_config_entry_diagnostics
from custom_components.shmu.shmu_opendata import ForecastStep
from custom_components.shmu.weather import _aggregate_daily

from .test_init import _FakeClient


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> MockConfigEntry:
    # Pin the zone so local-day grouping of the daily forecast is deterministic.
    await hass.config.async_set_time_zone("Europe/Bratislava")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="11858",
        title="Hurbanovo",
        data={CONF_IND_KLI: 11858},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


@pytest.fixture
def frozen_now() -> Iterator[datetime]:
    """Pin the weather entity's clock inside the ALADIN fixture's window.

    ``async_forecast_hourly`` trims hours that have already elapsed, and the
    fixtures are a real 2026-05-17 12:00Z run. Against the real wall clock every
    step is in the past, so the hourly forecast would be empty. ``dt_util.utcnow``
    is a cached ``functools.partial`` that ``freeze_time`` cannot intercept, so
    patch the module-level reference (same approach as ``test_init``).
    """
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    with patch("custom_components.shmu.weather.dt_util.utcnow", lambda: now):
        yield now


async def _forecasts(hass: HomeAssistant, kind: str) -> list[dict]:
    result = await hass.services.async_call(
        "weather",
        "get_forecasts",
        {"entity_id": "weather.hurbanovo", "type": kind},
        blocking=True,
        return_response=True,
    )
    return result["weather.hurbanovo"]["forecast"]


async def test_weather_supports_forecast_features(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    state = hass.states.get("weather.hurbanovo")
    assert state is not None
    feats = state.attributes["supported_features"]
    assert feats & WeatherEntityFeature.FORECAST_HOURLY
    assert feats & WeatherEntityFeature.FORECAST_DAILY


async def test_current_pressure_is_reduced_to_sea_level(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """The weather card's pressure is QFF, on the forecast's PRMSL datum.

    The observation reports station-level pressure (QFE, 1001.2 hPa at
    Hurbanovo's 115 m); the entity reduces it to sea level (~1015 hPa) so
    "now" and the forecast steps share a datum. Reporting the raw station
    value here (the old behaviour) would jump ~14 hPa against the forecast.
    """
    state = hass.states.get("weather.hurbanovo")
    assert state is not None
    assert state.attributes["pressure"] == pytest.approx(1015.06, abs=0.2)


async def test_hourly_forecast_shape_and_values(
    hass: HomeAssistant, setup_entry: MockConfigEntry, frozen_now: datetime
) -> None:
    hourly = await _forecasts(hass, "hourly")
    # Fixtures cover forecast hours 0, 1, 2, 24; "now" is pinned to the run
    # start so none have elapsed and all four survive the trim.
    assert len(hourly) == 4
    assert [f["datetime"] for f in hourly] == sorted(f["datetime"] for f in hourly)

    first = hourly[0]
    assert datetime.fromisoformat(first["datetime"])  # parseable, tz-aware
    assert -30.0 < first["temperature"] < 45.0
    assert first["condition"] is not None
    assert 0 <= first["cloud_coverage"] <= 100
    assert first["wind_speed"] >= 0.0
    # Hour 1 of this real run is a wet step.
    assert hourly[1]["precipitation"] >= 0.0
    assert any(f["condition"] == "rainy" for f in hourly)


async def test_daily_forecast_aggregates_by_local_day(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    daily = await _forecasts(hass, "daily")
    # Hours 0/1/2 fall on 2026-05-17 (local); hour 24 (a single 14:00 local
    # sample) is the only step on 2026-05-18, which the model horizon does not
    # cover to its end, so that truncated day is dropped rather than summarised
    # from morning-only data. See test_daily_forecast_drops_truncated_final_day.
    assert len(daily) == 1
    day0 = daily[0]
    assert day0["datetime"].startswith("2026-05-17")
    assert day0["templow"] <= day0["temperature"]  # low <= high
    assert day0["precipitation"] >= 0.0
    assert day0["condition"] is not None


def _step(when: datetime, temperature: float) -> ForecastStep:
    """A minimal dry forecast step at ``when`` for daily-aggregation tests."""
    return ForecastStep(
        time=when,
        temperature=temperature,
        precipitation=0.0,
        wind_speed=1.0,
        wind_gust=2.0,
        wind_bearing=180.0,
        pressure=1000.0,
        cloud_coverage=50.0,
        cape=0.0,
        condition="partlycloudy",
    )


async def test_daily_forecast_drops_truncated_final_day(hass: HomeAssistant) -> None:
    """A final day the +102 h horizon does not fully cover is not summarised.

    The real failure: a 00 UTC run reaches only ~08:00 local on its last day,
    so that day's bucket holds pre-dawn/morning steps whose ``max`` temperature
    is the overnight value — the true afternoon peak is simply absent. Emitting
    it would show a whole-day "high" far below reality.
    """
    await hass.config.async_set_time_zone("Europe/Bratislava")  # CEST = UTC+2

    # A full local day for the 21st: UTC 22:00 (20th) → 21:00 (21st) covers
    # local 00:00 → 23:00. Peak warmth at local 15:00 (13:00 UTC).
    start = datetime(2026, 7, 20, 22, tzinfo=UTC)
    temps = [10.0 + 8.0 * (1 - abs((h - 15) / 15)) for h in range(24)]  # peak ~ 15L
    steps = [_step(start + timedelta(hours=h), temps[h]) for h in range(24)]

    # The truncated 22nd: only 00/03/06 UTC (local 02:00 to 08:00), all cool.
    tail = datetime(2026, 7, 22, 0, tzinfo=UTC)
    steps += [_step(tail + timedelta(hours=h), 13.0) for h in (0, 3, 6)]

    daily = _aggregate_daily(steps)

    assert [d["datetime"][:10] for d in daily] == ["2026-07-21"]
    # The kept day's high is the genuine afternoon peak, not a morning slice.
    assert daily[0]["native_temperature"] == pytest.approx(max(temps))


async def test_daily_forecast_keeps_full_days_before_truncated_tail(
    hass: HomeAssistant,
) -> None:
    """Full days are kept; only the truncated tail after them is dropped.

    Mirrors a real contiguous run: every full day has trailing steps reaching
    into the (partial) next day, so its horizon passes local midnight and it is
    summarised. This guards against the drop being too aggressive.
    """
    await hass.config.async_set_time_zone("Europe/Bratislava")

    start = datetime(2026, 7, 20, 22, tzinfo=UTC)  # local 00:00 on the 21st
    # 21st and 22nd fully covered, then a morning-only 23rd (the truncated tail).
    steps = [
        _step(start + timedelta(hours=h), 15.0 + (h % 24) * 0.5) for h in range(48)
    ]
    tail = datetime(2026, 7, 23, 0, tzinfo=UTC)  # local 02:00 on the 23rd
    steps += [_step(tail + timedelta(hours=h), 13.0) for h in (0, 3, 6)]

    daily = _aggregate_daily(steps)

    assert [d["datetime"][:10] for d in daily] == ["2026-07-21", "2026-07-22"]


async def test_hourly_forecast_trims_elapsed_hours(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Steps before the current hour are dropped so no past hours are shown.

    A run is published from its reference time onward, so the raw list leads
    with hours that have already elapsed until the next run lands. The hourly
    forecast must begin at the current hour, not the run start.
    """
    # 13:30Z → cutoff 13:00Z drops the 12:00 step (hour 0); 13:00/14:00/next-day
    # remain. The in-progress hour (13:00) is kept, not skipped.
    now = datetime(2026, 5, 17, 13, 30, tzinfo=UTC)
    with patch("custom_components.shmu.weather.dt_util.utcnow", lambda: now):
        hourly = await _forecasts(hass, "hourly")

    assert len(hourly) == 3
    assert hourly[0]["datetime"] == "2026-05-17T13:00:00+00:00"
    cutoff = now.replace(minute=0)
    assert all(datetime.fromisoformat(f["datetime"]) >= cutoff for f in hourly)


async def test_daily_forecast_keeps_full_day_when_hours_elapsed(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Daily aggregation is not trimmed: today still summarises the whole day.

    The hourly trim must not leak into the daily path, or today's high/low
    would be computed from only the remaining hours.
    """
    now = datetime(2026, 5, 17, 23, 30, tzinfo=UTC)
    with patch("custom_components.shmu.weather.dt_util.utcnow", lambda: now):
        daily = await _forecasts(hass, "daily")

    # 2026-05-17 is still summarised from all of hours 0/1/2 even though every
    # one is well in the past relative to "now" — the elapsed-hours trim is
    # confined to the hourly path. (The 18th is a truncated final day and is
    # dropped for a separate reason; see the horizon tests above.)
    assert [d["datetime"][:10] for d in daily] == ["2026-05-17"]


async def test_dataset_freshness_diagnostics(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Released/fetched diagnostics surface each in-use dataset's timestamps."""

    def state_for(unique_id: str) -> str:
        entity_id = entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"11858_{unique_id}"
        )
        assert entity_id is not None, unique_id
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        return state.state

    # The forecast's "released" timestamp is the model run's reference time.
    assert state_for("forecast_run") == "2026-05-17T12:00:00+00:00"
    # Fetch times are real wall-clock instants — present and tz-aware.
    for key in ("observation_fetched", "forecast_fetched"):
        assert datetime.fromisoformat(state_for(key)).tzinfo is not None
    # The fixture server omits Last-Modified, so the observation release time is
    # genuinely unknown rather than silently faked.
    assert state_for("observation_released") == STATE_UNKNOWN


async def test_diagnostics_includes_forecast_provenance(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    diag = await async_get_config_entry_diagnostics(hass, setup_entry)
    fc = diag["forecast"]
    assert fc is not None
    assert fc["source"] == "test-run/20260517/1200"
    assert fc["step_count"] == 4
    assert len(fc["grid_point"]) == 2
    assert fc["first_step"] is not None


async def test_current_forecast_step_picks_nearest_within_tolerance(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """The ALADIN gap-filler uses the step nearest 'now', ignoring stale runs.

    Fixture run is 2026-05-17 12:00Z with steps at hours 0/1/2/24.
    """
    data = setup_entry.runtime_data.data

    # 13:10Z is closest to the 13:00 step (hour 1), comfortably within tolerance.
    near = data.current_forecast_step(datetime(2026, 5, 17, 13, 10, tzinfo=UTC))
    assert near is not None
    assert near.time == datetime(2026, 5, 17, 13, 0, tzinfo=UTC)

    # 18:00Z is >90 min from every step (the next is the hour-24 day-later one),
    # so the run no longer stands in for the present.
    assert data.current_forecast_step(datetime(2026, 5, 17, 18, 0, tzinfo=UTC)) is None
