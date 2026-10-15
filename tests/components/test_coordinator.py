"""Unit tests for coordinator-level forecast assembly helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from homeassistant.util import dt as dt_util

from custom_components.shmu.const import (
    RADAR_ECHO_STALE_AFTER,
    WEB_CONDITIONS_STALE_AFTER,
)
from custom_components.shmu.coordinator import (
    ShmuData,
    _accumulations_tile,
    _merge_forecast_runs,
)
from custom_components.shmu.shmu_opendata import (
    ForecastSnapshot,
    ForecastStep,
    LocalEcho,
    Observation,
    ObservationSnapshot,
    RadarFrame,
    WebCondition,
    WebConditionsSnapshot,
    get_station,
)
from custom_components.shmu.shmu_opendata.client import _radar_snapshot, _render_frame

# Europe/Bratislava is UTC+2 in July, so local midnight on the 21st is 22:00 UTC
# on the 20th. The helper compares instants, so a UTC-aware value is enough.
_DAY_START = datetime(2026, 7, 20, 22, tzinfo=UTC)


def _step(when: datetime, run: datetime, span: float = 1.0) -> ForecastStep:
    return ForecastStep(
        time=when,
        temperature=15.0,
        precipitation=0.0,
        wind_speed=1.0,
        wind_gust=2.0,
        wind_bearing=180.0,
        pressure=1000.0,
        cloud_coverage=50.0,
        cape=0.0,
        temperature_850hpa=None,
        freezing_level=None,
        condition="partlycloudy",
        span_hours=span,
        run=run,
    )


def _snap(
    source: str,
    start: datetime,
    hours: list[int],
) -> ForecastSnapshot:
    """A snapshot of ``hours`` after ``start``, spans set as within one run."""
    steps, prev = [], None
    for hour in hours:
        span = hour - prev if prev is not None else hour
        steps.append(
            _step(start + timedelta(hours=hour), start, float(span) if span else 1.0)
        )
        prev = hour
    return ForecastSnapshot(
        steps=steps,
        run=start,
        source=source,
        forecast_hours=tuple(hours),
        grid_point=(10, 20),
        fetched_at=start,
    )


def test_merge_backfills_earlier_hours_from_previous_run() -> None:
    # Previous run covers the whole 21st from local midnight (22:00 UTC 20th);
    # the newer run starts at 06:00 UTC (08:00 local), missing the morning.
    previous = _snap("run-A", datetime(2026, 7, 20, 22, tzinfo=UTC), list(range(12)))
    current = _snap("run-B", datetime(2026, 7, 21, 6, tzinfo=UTC), list(range(12)))

    merged = _merge_forecast_runs(previous, current, _DAY_START)

    assert merged is not None
    # The morning (22:00 UTC 20th .. 05:00 UTC 21st) comes from run-A, then
    # run-B's steps follow, with no gap or overlap at the seam.
    assert merged.steps[0].time == datetime(2026, 7, 20, 22, tzinfo=UTC)
    assert merged.steps[-1].time == datetime(2026, 7, 21, 17, tzinfo=UTC)
    times = [s.time for s in merged.steps]
    assert times == sorted(times)
    assert len(times) == len(set(times))  # no duplicated valid times
    assert _accumulations_tile(merged.steps)
    # Provenance still identifies the newest run, per step and for the snapshot.
    assert merged.source == "run-B"
    assert merged.steps[0].run == datetime(2026, 7, 20, 22, tzinfo=UTC)
    assert merged.steps[-1].run == datetime(2026, 7, 21, 6, tzinfo=UTC)


def test_merge_keeps_the_longer_reach_of_the_previous_run() -> None:
    """A newer but shorter run must not shorten the forecast's horizon.

    The real case: only the 00 UTC run publishes +102 h, the others stop at
    +72 h. Letting a newer short run replace the series outright would drop a
    whole day from the daily forecast, trading a day for the freshness.
    """
    previous = _snap("run-A", datetime(2026, 7, 20, 22, tzinfo=UTC), list(range(30)))
    current = _snap("run-B", datetime(2026, 7, 21, 6, tzinfo=UTC), list(range(12)))

    merged = _merge_forecast_runs(previous, current, _DAY_START)

    assert merged is not None
    # run-B's own last step is 17:00; run-A's tail carries the series to 03:00.
    assert merged.steps[-1].time == datetime(2026, 7, 22, 3, tzinfo=UTC)
    assert _accumulations_tile(merged.steps)
    # Everything run-B covers comes from run-B; only the tail is older.
    covered = {s.time for s in current.steps}
    assert all(s.run == current.run for s in merged.steps if s.time in covered)
    assert all(s.run == previous.run for s in merged.steps if s.time not in covered)


def test_merge_bounds_the_series_to_the_local_day() -> None:
    # Previous run reaches back into the 20th; those steps must not survive,
    # or the daily aggregation would emit a stale past day.
    previous = _snap("run-A", datetime(2026, 7, 20, 12, tzinfo=UTC), list(range(24)))
    current = _snap("run-B", datetime(2026, 7, 21, 6, tzinfo=UTC), list(range(6)))

    merged = _merge_forecast_runs(previous, current, _DAY_START)

    assert merged is not None
    assert all(s.time >= _DAY_START for s in merged.steps)


def test_merge_rebounds_the_day_even_when_the_run_is_unchanged() -> None:
    """A day rolling over must drop yesterday without waiting for a new run.

    Between local midnight and the next run being published the newest run is
    unchanged, so a cache hit hands back the same snapshot — whose steps still
    begin on the day that just ended. Left untrimmed, the daily forecast's
    leading entry would be *yesterday* for those hours.
    """
    snapshot = _snap("run-A", datetime(2026, 7, 20, 12, tzinfo=UTC), list(range(36)))

    # Same object both sides, exactly as the client's cache hit returns it.
    merged = _merge_forecast_runs(snapshot, snapshot, _DAY_START)

    assert merged is not None
    assert merged.steps
    assert all(s.time >= _DAY_START for s in merged.steps)


def test_merge_without_a_previous_snapshot_still_bounds_the_day() -> None:
    current = _snap("run-B", datetime(2026, 7, 20, 12, tzinfo=UTC), list(range(24)))

    merged = _merge_forecast_runs(None, current, _DAY_START)

    assert merged is not None
    assert all(s.time >= _DAY_START for s in merged.steps)


def test_merge_of_a_full_four_run_day_tiles() -> None:
    """The real shape: a 00 UTC +102 h run plus three +72 h runs.

    Each run is folded in as it is published; the series must stay
    self-consistent throughout and keep the 00 UTC run's longer reach.
    """
    day = datetime(2026, 7, 20, 22, tzinfo=UTC)  # local midnight on the 21st
    long_hours = [*range(49), *range(51, 103, 3)]
    short_hours = [h for h in long_hours if h <= 72]

    snapshot = _snap("run-00", datetime(2026, 7, 21, tzinfo=UTC), long_hours)
    for hour in (6, 12, 18):
        current = _snap(
            f"run-{hour:02d}",
            datetime(2026, 7, 21, hour, tzinfo=UTC),
            short_hours,
        )
        merged = _merge_forecast_runs(snapshot, current, day)
        assert merged is not None
        assert _accumulations_tile(merged.steps), f"{hour:02d} UTC run broke tiling"
        snapshot = merged

    # The 00 UTC run's horizon survives all three folds...
    assert snapshot.steps[-1].time == datetime(2026, 7, 25, 6, tzinfo=UTC)
    # ...while the near term is served by the newest run.
    assert snapshot.steps[0].run == datetime(2026, 7, 21, tzinfo=UTC)
    assert snapshot.run == datetime(2026, 7, 21, 18, tzinfo=UTC)
    contributing = {s.run for s in snapshot.steps}
    assert len(contributing) == 4


def test_merge_orders_the_series_regardless_of_input_order() -> None:
    """Chronological order is the helper's own guarantee, not the caller's.

    ``_accumulations_tile`` reads each step against its predecessor, so an
    out-of-order input would make the windows look mismatched and needlessly
    drop the merge. Decoded runs happen to arrive ordered; the helper does not
    rely on it.
    """
    current = _snap("run-B", datetime(2026, 7, 21, 6, tzinfo=UTC), list(range(6)))
    shuffled = replace(current, steps=list(reversed(current.steps)))

    merged = _merge_forecast_runs(None, shuffled, _DAY_START)

    assert merged is not None
    times = [s.time for s in merged.steps]
    assert times == sorted(times)
    assert _accumulations_tile(merged.steps)


def test_merge_opts_out_when_the_windows_stop_tiling() -> None:
    """Mismatched step spacing must degrade, not double-count rain.

    Merging assumes each run's step times are a subset of any denser run
    overlapping them. If SHMÚ ever changes the spacing that breaks, and an
    older sparse step can land between newer dense ones — its 3 h of rain
    counted against a 1 h gap. The merge is dropped rather than served.
    """
    start = datetime(2026, 7, 20, 22, tzinfo=UTC)
    # Previous run is 3-hourly; the newer run is hourly but offset, so the old
    # 3-hourly steps do not coincide with any new step and survive the merge.
    previous = _snap("run-A", start, [0, 3, 6, 9])
    current = _snap("run-B", start + timedelta(minutes=30), [0, 1, 2, 3, 4, 5])

    merged = _merge_forecast_runs(previous, current, _DAY_START)

    assert merged is not None
    # Fell back to the newest run alone: self-consistent and freshest.
    assert {s.run for s in merged.steps} == {current.run}
    assert _accumulations_tile(merged.steps)


def test_accumulations_tile_detects_a_double_counted_window() -> None:
    start = datetime(2026, 7, 21, tzinfo=UTC)
    run = start
    # A 3 h accumulation sitting only 1 h after its predecessor overlaps it.
    steps = [
        _step(start, run, 1.0),
        _step(start + timedelta(hours=1), run, 1.0),
        _step(start + timedelta(hours=2), run, 3.0),
    ]
    assert not _accumulations_tile(steps)
    assert _accumulations_tile(steps[:2])
    assert _accumulations_tile([])  # nothing to contradict


def _web_data(fetched_at: datetime) -> ShmuData:
    """Coordinator data whose only condition source is a website scrape."""
    ind_kli = 11858
    return ShmuData(
        observations=ObservationSnapshot(
            observations={}, source="t", fetched_at=fetched_at, published_at=None
        ),
        warnings=None,
        web_conditions=WebConditionsSnapshot(
            conditions={
                ind_kli: WebCondition(
                    ind_kli=ind_kli,
                    cloud_text="Zamračené",
                    weather_text="Dážď",
                    weather_condition="rainy",
                    cloud_condition="cloudy",
                    condition="rainy",
                )
            },
            fetched_at=fetched_at,
        ),
        forecast=None,
        radar=None,
        gauge_observations=None,
    )


def test_recent_website_conditions_win_the_ladder() -> None:
    station = get_station(11858)
    assert station is not None
    data = _web_data(dt_util.utcnow() - timedelta(minutes=5))

    assert data.resolve_condition(station, None) == ("rainy", "website")
    assert not data.web_conditions_ignored(dt_util.utcnow())


def test_stale_website_conditions_do_not_win_the_ladder() -> None:
    """A scrape kept through a long website outage must stop pinning the state.

    Website conditions sit at the top of the ladder, and a failed scrape keeps
    the previous snapshot — so without an age limit, an outage of hours would
    hold the condition at whatever the page last said.
    """
    station = get_station(11858)
    assert station is not None
    data = _web_data(
        dt_util.utcnow() - WEB_CONDITIONS_STALE_AFTER - timedelta(minutes=1)
    )

    assert data.resolve_condition(station, None) == (None, "unknown")
    assert data.web_conditions_ignored(dt_util.utcnow())


def _radar_data(valid_at: datetime, echo: LocalEcho | None) -> ShmuData:
    """Coordinator data whose only condition source is a radar frame."""
    payload = (Path(__file__).parents[1] / "fixtures" / "radar_zmax.hdf").read_bytes()
    station = get_station(11858)
    assert station is not None
    image, map_image, _ = _render_frame(
        payload, station.latitude, station.longitude, "label"
    )
    frame = RadarFrame(
        image=image, map_image=map_image, source="t", valid_at=valid_at, echo=echo
    )
    return ShmuData(
        observations=ObservationSnapshot(
            observations={}, source="t", fetched_at=valid_at, published_at=None
        ),
        warnings=None,
        web_conditions=None,
        forecast=None,
        radar=_radar_snapshot([frame], "zmax"),
        gauge_observations=None,
    )


def test_a_current_radar_echo_enters_the_ladder() -> None:
    station = get_station(11858)
    assert station is not None
    # A frame reaches the listing ~6 min after its nominal time.
    data = _radar_data(dt_util.utcnow() - timedelta(minutes=8), LocalEcho(30.0))

    assert data.resolve_condition(station, None) == ("rainy", "radar")


def test_a_stale_radar_frame_says_nothing() -> None:
    """A held frame from a radar that stopped updating must not assert rain,
    nor (more importantly) keep vetoing the model's."""
    station = get_station(11858)
    assert station is not None
    data = _radar_data(
        dt_util.utcnow() - RADAR_ECHO_STALE_AFTER - timedelta(minutes=1),
        LocalEcho(30.0),
    )

    assert data.current_radar_echo(dt_util.utcnow()) is None
    assert data.resolve_condition(station, None) == (None, "unknown")


def _observation(ind_kli: int, weather_code: int) -> Observation:
    """A dry reading carrying only what the condition ladder reads."""
    return Observation(
        ind_kli=ind_kli,
        measured_at=dt_util.utcnow(),
        temperature=None,
        humidity=None,
        pressure=None,
        wind_speed=None,
        wind_gust=None,
        wind_bearing=None,
        precipitation=0.0,
        snow_depth=None,
        visibility=None,
        ground_temperature=None,
        global_radiation=None,
        weather_code=weather_code,
        raw={},
    )


def test_untrusted_present_weather_sensor_cannot_claim_rain() -> None:
    """The station's flag reaches the ladder: its drizzle code is left out."""
    data = replace(_web_data(dt_util.utcnow()), web_conditions=None)
    banska_bystrica = get_station(11898)
    hurbanovo = get_station(11858)
    assert banska_bystrica is not None and hurbanovo is not None
    assert banska_bystrica.untrusted_precipitation_codes

    resolution = data.explain_condition(banska_bystrica, _observation(11898, 51))
    assert (resolution.condition, resolution.source) == (None, "unknown")
    assert resolution.ignored_weather_code == 51
    # The same code from a sound sensor is believed.
    assert data.resolve_condition(hurbanovo, _observation(11858, 51)) == (
        "rainy",
        "stav_poc",
    )
