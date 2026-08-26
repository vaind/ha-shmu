"""Tests for the ALADIN upper-air sensors (issue #44).

The two are model-derived rather than measured, which shapes both their
availability (they follow the coordinator's recent success, not a station
reading) and their default state (opt-in, so a household that will never look
at an 850 hPa temperature never sees one).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import CONF_IND_KLI, DOMAIN
from custom_components.shmu.shmu_opendata import ForecastStep

from .test_init import _FakeClient

_FREEZING_LEVEL = "sensor.hurbanovo_freezing_level"
_T850 = "sensor.hurbanovo_temperature_at_850_hpa"


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    config_entry = MockConfigEntry(
        domain=DOMAIN, unique_id="11858", title="Hurbanovo", data={CONF_IND_KLI: 11858}
    )
    config_entry.add_to_hass(hass)
    return config_entry


def _step(
    when: datetime,
    *,
    freezing_level: float | None,
    temperature_850hpa: float | None,
) -> ForecastStep:
    """A model step carrying only what these sensors read."""
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
        temperature_850hpa=temperature_850hpa,
        freezing_level=freezing_level,
        condition="partlycloudy",
        span_hours=1.0,
        run=when,
    )


async def _setup_with_upper_air(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    load: Callable[[str], bytes],
    *,
    freezing_level: float | None = 2450.0,
    temperature_850hpa: float | None = -3.5,
    offset: timedelta = timedelta(0),
) -> None:
    """Set up the entry, enable the opt-in sensors, and hold a step carrying them.

    The GRIB2 fixtures behind the fake client are the trimmed *surface-only*
    files, so the held run's steps are replaced with ones that carry the two
    values: what is under test here is the entity. The decoding itself is
    covered against a real upper-air file in ``tests/test_forecast.py``.

    ``offset`` moves the step away from the present, for the case where a held
    run no longer covers it.
    """
    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        for key in ("freezing_level", "temperature_850hpa"):
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"11858_{key}")
            assert entity_id is not None, f"{key} sensor was never registered"
            assert registry.async_get(entity_id).disabled  # opt-in by default
            registry.async_update_entity(entity_id, disabled_by=None)

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data
    forecast = coordinator.data.forecast
    assert forecast is not None
    coordinator.data.forecast = replace(
        forecast,
        steps=[
            _step(
                datetime.now(UTC) + offset,
                freezing_level=freezing_level,
                temperature_850hpa=temperature_850hpa,
            )
        ],
    )
    coordinator.async_update_listeners()
    await hass.async_block_till_done()


async def test_upper_air_sensors_report_the_current_step(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    await _setup_with_upper_air(hass, entry, load)

    freezing_level = hass.states.get(_FREEZING_LEVEL)
    assert freezing_level is not None
    assert float(freezing_level.state) == pytest.approx(2450.0)
    assert freezing_level.attributes["unit_of_measurement"] == "m"
    assert freezing_level.attributes["device_class"] == "distance"

    t850 = hass.states.get(_T850)
    assert t850 is not None
    assert float(t850.state) == pytest.approx(-3.5)
    assert t850.attributes["unit_of_measurement"] == "°C"


async def test_upper_air_sensors_unknown_without_the_fields(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """A run whose files carry no pressure levels must not invent a value."""
    await _setup_with_upper_air(
        hass, entry, load, freezing_level=None, temperature_850hpa=None
    )

    # Unknown, but still *available*: the run is held, the quantity is not in it.
    assert hass.states.get(_FREEZING_LEVEL).state == "unknown"
    assert hass.states.get(_T850).state == "unknown"


async def test_upper_air_sensors_unknown_when_no_step_covers_now(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """A held run too stale to reach the present contributes nothing.

    Observations can keep succeeding while the forecast fetch fails, so the
    coordinator is healthy (the entities stay available) but its newest step is
    hours away from now — the same case in which the condition ladder stops
    consulting the model.
    """
    await _setup_with_upper_air(hass, entry, load, offset=timedelta(days=2))

    assert hass.states.get(_FREEZING_LEVEL).state == "unknown"
    assert hass.states.get(_T850).state == "unknown"


def test_forecast_step_states_its_upper_air_fields() -> None:
    """No defaults: a step must say what it knows about the profile.

    Defaulting them to ``None`` would let a future construction site drop the
    upper air silently, which reads exactly like a run that never carried it.
    """
    with pytest.raises(TypeError):
        ForecastStep(  # type: ignore[call-arg]
            time=datetime.now(UTC),
            temperature=None,
            precipitation=None,
            wind_speed=None,
            wind_gust=None,
            wind_bearing=None,
            pressure=None,
            cloud_coverage=None,
            cape=None,
            condition=None,
            span_hours=1.0,
            run=datetime.now(UTC),
        )
