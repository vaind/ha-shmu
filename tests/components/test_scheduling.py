"""Grid-boundary maths and adaptive-offset tests."""

from __future__ import annotations

from datetime import UTC, datetime

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
