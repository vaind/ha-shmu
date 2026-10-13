"""Grid-boundary maths and adaptive-offset tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import (
    CONF_IND_KLI,
    DOMAIN,
    POLL_OFFSET_MAX_SECONDS,
    POLL_OFFSET_MIN_SECONDS,
)
from custom_components.shmu.coordinator import (
    ShmuDataUpdateCoordinator,
    _next_grid_time,
)
from custom_components.shmu.shmu_opendata import ObservationSnapshot


def test_next_grid_time_is_strictly_future_and_aligned() -> None:
    f = datetime(2026, 5, 17, 18, 3, 12, 500000, tzinfo=UTC)
    assert _next_grid_time(f, 5) == datetime(2026, 5, 17, 18, 5, tzinfo=UTC)
    # Exactly on a boundary -> the *next* one (strictly after).
    assert _next_grid_time(datetime(2026, 5, 17, 18, 5, tzinfo=UTC), 5) == datetime(
        2026, 5, 17, 18, 10, tzinfo=UTC
    )
    # Hour rollover.
    assert _next_grid_time(
        datetime(2026, 5, 17, 18, 59, 30, tzinfo=UTC), 5
    ) == datetime(2026, 5, 17, 19, 0, tzinfo=UTC)


def _snapshot(published_at: datetime | None) -> ObservationSnapshot:
    return ObservationSnapshot(
        observations={},
        source="t",
        fetched_at=published_at or datetime.now(UTC),
        published_at=published_at,
    )


async def test_offset_auto_tunes_to_publish_lag(hass: HomeAssistant) -> None:
    config_entry = MockConfigEntry(domain=DOMAIN, data={CONF_IND_KLI: 11858})
    coordinator = ShmuDataUpdateCoordinator(hass, config_entry, object())

    # No samples yet -> just the fixed pad (== the floor).
    assert coordinator._offset_seconds() == POLL_OFFSET_MIN_SECONDS

    # Published 40 s after its 5-min grid boundary -> offset = 40 + pad.
    coordinator._record_publish_lag(
        _snapshot(datetime(2026, 5, 17, 18, 5, 40, tzinfo=UTC))
    )
    assert coordinator._offset_seconds() == 70

    # A pathological late sample is clamped to the ceiling.
    coordinator._record_publish_lag(
        _snapshot(datetime(2026, 5, 17, 18, 9, 0, tzinfo=UTC))
    )
    assert coordinator._offset_seconds() == POLL_OFFSET_MAX_SECONDS

    # A missing Last-Modified header is ignored (no crash, no sample).
    coordinator._record_publish_lag(_snapshot(None))


async def test_unload_during_a_refresh_does_not_rearm_the_timer(
    hass: HomeAssistant,
) -> None:
    """A refresh in flight at unload must not schedule the next poll.

    The scheduled handler clears its own timer handle before awaiting the
    refresh and re-arms afterwards. An unload (or an options-change reload)
    landing in that window finds no timer to cancel, so without an explicit
    stop the handler would re-arm a timer for the dead coordinator — and keep
    re-arming it, holding the coordinator and its radar buffers, for ever.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={CONF_IND_KLI: 11858})
    coordinator = ShmuDataUpdateCoordinator(hass, config_entry, object())
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_refresh() -> None:
        started.set()
        await release.wait()

    with patch.object(coordinator, "async_request_refresh", _slow_refresh):
        task = hass.async_create_task(
            coordinator._handle_scheduled_refresh(datetime.now(UTC))
        )
        await started.wait()

        coordinator.async_cancel_refresh()
        release.set()
        await task

    assert coordinator._unsub_refresh is None
    # And a late re-arm attempt from anywhere else is refused too.
    coordinator.async_schedule_refresh()
    assert coordinator._unsub_refresh is None
