"""Weather-warning calendar tests (warnings served by the stubbed client)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import (
    CONF_IND_KLI,
    CONF_LOCATION,
    CONF_LOCATION_MODE,
    DOMAIN,
    LOCATION_MODE_CUSTOM,
)
from custom_components.shmu.shmu_opendata import Warning, WarningsSnapshot
from custom_components.shmu.shmu_opendata.parsers import parse_cap_alert

from .test_init import _BRATISLAVA, _FakeClient

_CALENDAR = "calendar.bratislava_weather_warnings"
_BINARY_SENSOR = "binary_sensor.bratislava_weather_warning"


class _WarningsClient(_FakeClient):
    """Serves the given warnings instead of the fixture alert."""

    def __init__(self, load: Callable[[str], bytes], warnings: list[Warning]) -> None:
        super().__init__(load)
        self.warnings = warnings

    async def async_get_warnings(self, previous=None) -> WarningsSnapshot:
        return WarningsSnapshot(
            warnings=self.warnings, source="test", fetched_at=datetime.now(UTC)
        )


def _now() -> datetime:
    # The calendar decides its state on Home Assistant's real clock, so the
    # warnings are placed around the real time rather than a patched one.
    return datetime.now(UTC).replace(second=0, microsecond=0)


def _warning(
    load: Callable[[str], bytes],
    event: str,
    onset: datetime,
    expires: datetime,
    *,
    instruction: str | None = "ZVÝŠTE POZORNOSŤ.",
) -> Warning:
    """The fixture alert (over Bratislava) with its name, times and text replaced."""
    return replace(
        parse_cap_alert(load("alert.cap.xml")),
        identifier=f"test.{event}",
        event=event,
        onset=onset,
        expires=expires,
        description=f"{event}: popis.",
        instruction=instruction,
    )


async def _setup(
    hass: HomeAssistant, load: Callable[[str], bytes], warnings: list[Warning]
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="11858",
        title="Bratislava",
        data={CONF_IND_KLI: 11858, CONF_NAME: "Bratislava"},
        options={
            CONF_LOCATION_MODE: LOCATION_MODE_CUSTOM,
            CONF_LOCATION: {
                CONF_LATITUDE: _BRATISLAVA[0],
                CONF_LONGITUDE: _BRATISLAVA[1],
            },
        },
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.shmu.ShmuClient",
        return_value=_WarningsClient(load, warnings),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def _events(
    hass: HomeAssistant, start: datetime, end: datetime
) -> list[dict[str, str]]:
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": _CALENDAR,
            "start_date_time": start.isoformat(),
            "end_date_time": end.isoformat(),
        },
        blocking=True,
        return_response=True,
    )
    return response[_CALENDAR]["events"]


def _span(event: dict[str, str]) -> tuple[datetime, datetime]:
    return datetime.fromisoformat(event["start"]), datetime.fromisoformat(event["end"])


async def test_calendar_holds_active_and_upcoming_warnings(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    now = _now()
    active = _warning(
        load, "Výstraha pred dažďom", now - timedelta(hours=1), now + timedelta(hours=2)
    )
    upcoming = _warning(
        load,
        "Výstraha pred snežením",
        now + timedelta(hours=5),
        now + timedelta(hours=20),
        instruction=None,
    )
    expired = _warning(
        load, "Výstraha pred vetrom", now - timedelta(hours=6), now - timedelta(hours=2)
    )
    await _setup(hass, load, [upcoming, expired, active])

    events = await _events(hass, now - timedelta(days=1), now + timedelta(days=2))

    # Ordered by onset, and the expired warning stays out.
    assert [e["summary"] for e in events] == [active.event, upcoming.event]
    assert _span(events[0]) == (active.onset, active.expires)
    assert _span(events[1]) == (upcoming.onset, upcoming.expires)
    assert events[0]["description"] == (
        "Výstraha pred dažďom: popis.\n\nZVÝŠTE POZORNOSŤ."
    )
    assert events[1]["description"] == "Výstraha pred snežením: popis."

    state = hass.states.get(_CALENDAR)
    assert state.state == "on"
    assert state.attributes["message"] == active.event

    # The binary sensor still lists only the warning in force.
    assert hass.states.get(_BINARY_SENSOR).attributes["warning_count"] == 1


async def test_calendar_events_are_limited_to_the_requested_range(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    now = _now()
    active = _warning(
        load, "Výstraha pred dažďom", now - timedelta(hours=1), now + timedelta(hours=2)
    )
    upcoming = _warning(
        load,
        "Výstraha pred snežením",
        now + timedelta(hours=5),
        now + timedelta(hours=20),
    )
    await _setup(hass, load, [active, upcoming])

    # A range that only the upcoming warning overlaps.
    later = await _events(hass, now + timedelta(hours=3), now + timedelta(hours=6))
    assert [e["summary"] for e in later] == [upcoming.event]

    # A range that ends exactly at the upcoming warning's onset leaves it out.
    until_onset = await _events(hass, now, upcoming.onset)
    assert [e["summary"] for e in until_onset] == [active.event]

    # Nothing is known about the past beyond the warnings still in force.
    assert await _events(hass, now - timedelta(days=2), now - timedelta(days=1)) == []


async def test_calendar_shows_the_next_warning_before_it_starts(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    now = _now()
    later = _warning(
        load, "Výstraha pred vetrom", now + timedelta(hours=8), now + timedelta(hours=9)
    )
    sooner = _warning(
        load,
        "Výstraha pred snežením",
        now + timedelta(hours=5),
        now + timedelta(hours=20),
    )
    await _setup(hass, load, [later, sooner])

    state = hass.states.get(_CALENDAR)
    assert state.state == "off"
    assert state.attributes["message"] == sooner.event
    # Nothing is in force yet, so the binary sensor is off.
    assert hass.states.get(_BINARY_SENSOR).state == "off"


async def test_calendar_leaves_out_warnings_for_other_areas(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    now = _now()
    elsewhere = replace(
        _warning(
            load,
            "Výstraha pred dažďom",
            now - timedelta(hours=1),
            now + timedelta(hours=2),
        ),
        # A square around Košice, far from the Bratislava measurement location.
        polygons=(((48.6, 21.1), (48.6, 21.4), (48.8, 21.4), (48.8, 21.1)),),
    )
    await _setup(hass, load, [elsewhere])

    assert await _events(hass, now - timedelta(days=1), now + timedelta(days=1)) == []
    state = hass.states.get(_CALENDAR)
    assert state.state == "off"
    assert "message" not in state.attributes


async def test_calendar_state_shows_the_worst_warning_in_force(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    now = _now()
    yellow = _warning(
        load, "Výstraha pred dažďom", now - timedelta(hours=3), now + timedelta(hours=2)
    )
    orange = replace(
        _warning(
            load,
            "Výstraha pred búrkami",
            now - timedelta(hours=1),
            now + timedelta(hours=1),
        ),
        severity="Severe",
    )
    await _setup(hass, load, [yellow, orange])

    # The orange warning started later but is the more severe one.
    assert hass.states.get(_CALENDAR).attributes["message"] == orange.event
