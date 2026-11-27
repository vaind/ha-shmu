"""Calendar platform for SHMÚ Weather: the warnings issued for the location."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ShmuConfigEntry
from .entity import ShmuStationEntity
from .shmu_opendata import Warning

#: All entities read a single shared coordinator snapshot; there is no
#: per-entity device I/O to rate-limit, so updates need not be serialised.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SHMÚ warning calendar from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities([ShmuWarningCalendar(coordinator, coordinator.station)])


def _event(warning: Warning) -> CalendarEvent | None:
    """The calendar event spanning ``warning``.

    SHMÚ sends an onset and an expiry with every warning (see AGENTS.md), and
    one without either has no span to put on a calendar.
    """
    if warning.onset is None or warning.expires is None:
        return None
    text = [t for t in (warning.description, warning.instruction) if t]
    return CalendarEvent(
        start=warning.onset,
        end=warning.expires,
        summary=warning.event,
        description="\n\n".join(text) or None,
        uid=warning.identifier,
    )


class ShmuWarningCalendar(ShmuStationEntity, CalendarEntity):
    """One event per SHMÚ warning over the measurement location.

    Unlike the binary sensor, it also holds the warnings SHMÚ has issued that
    are not in force yet, so a calendar trigger can fire ahead of one.
    """

    _attr_translation_key = "weather_warnings"

    def __init__(self, coordinator, station) -> None:
        """Initialise the warning calendar."""
        super().__init__(coordinator, station)
        self._attr_unique_id = f"{station.ind_kli}_weather_warnings"

    @property
    def available(self) -> bool:
        """Available while a recent successful fetch backs the cached warnings.

        The same rule as the warning binary sensor's, independent of the
        station's reading.
        """
        return self.coordinator.has_recent_success

    def _events(self) -> list[CalendarEvent]:
        """The events of the warnings to show, worst severity first."""
        warnings = self.coordinator.data.unexpired_warnings_for(
            self.coordinator.location_latitude,
            self.coordinator.location_longitude,
        )
        return [event for w in warnings if (event := _event(w)) is not None]

    @property
    def event(self) -> CalendarEvent | None:
        """The worst warning in force, or else the next one to come into force."""
        events = self._events()
        now = dt_util.utcnow()
        in_force = (e for e in events if e.start <= now < e.end)
        if (current := next(in_force, None)) is not None:
            return current
        return min(events, key=lambda e: e.start, default=None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """The warnings overlapping the range, by onset."""
        return sorted(
            (e for e in self._events() if e.start < end_date and e.end > start_date),
            key=lambda e: (e.start, e.end),
        )
