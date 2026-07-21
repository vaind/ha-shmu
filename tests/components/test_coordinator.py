"""Unit tests for coordinator-level forecast assembly helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.shmu.coordinator import _extend_forecast_to_day_start
from custom_components.shmu.shmu_opendata import ForecastSnapshot, ForecastStep

# Europe/Bratislava is UTC+2 in July, so local midnight on the 21st is 22:00 UTC
# on the 20th. The helper compares instants, so a UTC-aware value is enough.
_DAY_START = datetime(2026, 7, 20, 22, tzinfo=UTC)


def _step(when: datetime) -> ForecastStep:
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
        condition="partlycloudy",
    )


def _snap(source: str, start: datetime, count: int) -> ForecastSnapshot:
    """A snapshot with ``count`` hourly steps from ``start``."""
    return ForecastSnapshot(
        steps=[_step(start + timedelta(hours=h)) for h in range(count)],
        run=start,
        source=source,
        grid_point=(10, 20),
        fetched_at=start,
    )


def test_extend_backfills_earlier_hours_from_previous_run() -> None:
    # Previous run covers the whole 21st from local midnight (22:00 UTC 20th);
    # the newer run starts at 06:00 UTC (08:00 local), missing the morning.
    previous = _snap("run-A", datetime(2026, 7, 20, 22, tzinfo=UTC), 12)
    current = _snap("run-B", datetime(2026, 7, 21, 6, tzinfo=UTC), 12)

    merged = _extend_forecast_to_day_start(previous, current, _DAY_START)

    assert merged is not None
    # The morning (22:00 UTC 20th .. 05:00 UTC 21st) is carried from run-A, then
    # run-B's steps follow, with no gap or overlap at the seam.
    assert merged.steps[0].time == datetime(2026, 7, 20, 22, tzinfo=UTC)
    assert merged.steps[-1].time == datetime(2026, 7, 21, 17, tzinfo=UTC)
    seam = [s.time for s in merged.steps]
    assert seam == sorted(seam)
    assert len(seam) == len(set(seam))  # no duplicated valid times
    # Provenance still identifies the newest run.
    assert merged.source == "run-B"


def test_extend_bounds_carry_to_the_local_day() -> None:
    # Previous run reaches back into the 20th; those steps must not be carried,
    # or the daily aggregation would emit a stale past day.
    previous = _snap("run-A", datetime(2026, 7, 20, 12, tzinfo=UTC), 24)
    current = _snap("run-B", datetime(2026, 7, 21, 6, tzinfo=UTC), 6)

    merged = _extend_forecast_to_day_start(previous, current, _DAY_START)

    assert merged is not None
    assert all(s.time >= _DAY_START for s in merged.steps)


def test_extend_is_noop_when_run_unchanged() -> None:
    current = _snap("run-B", datetime(2026, 7, 21, 6, tzinfo=UTC), 6)
    # Same source == cache hit: already-extended snapshot returned untouched.
    assert _extend_forecast_to_day_start(current, current, _DAY_START) is current


def test_extend_is_noop_when_run_already_covers_the_day() -> None:
    previous = _snap("run-A", datetime(2026, 7, 20, 22, tzinfo=UTC), 6)
    # Current starts at local midnight, so nothing needs carrying.
    current = _snap("run-B", datetime(2026, 7, 20, 22, tzinfo=UTC), 12)
    assert _extend_forecast_to_day_start(previous, current, _DAY_START) is current


def test_extend_is_noop_without_a_previous_snapshot() -> None:
    current = _snap("run-B", datetime(2026, 7, 21, 6, tzinfo=UTC), 6)
    assert _extend_forecast_to_day_start(None, current, _DAY_START) is current
