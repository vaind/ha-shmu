"""Tests for the sensor platform's entity semantics.

Covers the measured quantities whose device and state classes decide how Home
Assistant converts, graphs and aggregates them, and the ALADIN upper-air
sensors (issue #44). The latter are model-derived rather than measured, which
shapes both their availability (they follow the coordinator's recent success,
not a station reading) and their default state (opt-in, so a household that
will never look at an 850 hPa temperature never sees one).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import PropertyMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import CONF_IND_KLI, DOMAIN
from custom_components.shmu.coordinator import ShmuDataUpdateCoordinator
from custom_components.shmu.shmu_opendata import ForecastStep

from .test_init import _FakeClient

_FREEZING_LEVEL = "sensor.hurbanovo_freezing_level"
_T850 = "sensor.hurbanovo_temperature_at_850_hpa"
_PRECIPITATION = "sensor.hurbanovo_precipitation"
_GAUGE_PRECIPITATION = "sensor.hurbanovo_rain_gauge_precipitation"


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


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("entity_id", "minute_sum"),
    [
        # Station 11858's newest record, and the Kolárovo gauge (17720) nearest it.
        (_PRECIPITATION, 0.2),
        (_GAUGE_PRECIPITATION, 0.4),
    ],
)
async def test_precipitation_is_reported_as_an_hourly_rate(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    load: Callable[[str], bytes],
    entity_id: str,
    minute_sum: float,
) -> None:
    """SHMÚ's ``zra_uhrn`` is a 1-minute sum, sampled once per 5-minute file.

    Surfaced as an amount, four minutes in five would be silently missing from
    any total, so it is the *rate* that minute implies: an intensity, which a
    single sample honestly is.
    """
    await _setup(hass, entry, load)

    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == pytest.approx(minute_sum * 60)
    assert state.attributes["unit_of_measurement"] == "mm/h"
    assert state.attributes["device_class"] == "precipitation_intensity"
    assert state.attributes["state_class"] == "measurement"


async def test_precipitation_rate_drops_float_noise(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """``0.2 * 60`` is ``12.000000000000002`` in binary; the state must not say so."""
    await _setup(hass, entry, load)

    assert hass.states.get(_PRECIPITATION).state == "12.0"


async def test_missing_precipitation_is_unavailable(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """A reading without ``zra_uhrn`` is unavailable, not a rate of zero."""
    await _setup(hass, entry, load)
    coordinator = entry.runtime_data
    station = replace(coordinator.observation, precipitation=None)
    gauge = replace(coordinator.gauge_observation, precipitation=None)

    with (
        patch.object(
            ShmuDataUpdateCoordinator,
            "observation",
            new_callable=PropertyMock,
            return_value=station,
        ),
        patch.object(
            ShmuDataUpdateCoordinator,
            "gauge_observation",
            new_callable=PropertyMock,
            return_value=gauge,
        ),
    ):
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        assert hass.states.get(_PRECIPITATION).state == "unavailable"
        assert hass.states.get(_GAUGE_PRECIPITATION).state == "unavailable"
        # The station's other readings are unaffected.
        assert hass.states.get("sensor.hurbanovo_temperature").state == "12.1"


async def test_quantity_the_station_does_not_report_is_unavailable(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """Hurbanovo's fresh reading carries no ``sneh_pokr``: that one sensor is
    unavailable, not unknown, while the station's other readings update."""
    await _setup(hass, entry, load)

    assert hass.states.get("sensor.hurbanovo_snow_depth").state == "unavailable"
    assert hass.states.get("sensor.hurbanovo_visibility").state == "24000.0"


async def test_sea_level_pressure_unavailable_without_temperature(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """The reduction needs a real temperature; without one there is no value."""
    await _setup(hass, entry, load)
    coordinator = entry.runtime_data
    station = replace(coordinator.observation, temperature=None)

    with patch.object(
        ShmuDataUpdateCoordinator,
        "observation",
        new_callable=PropertyMock,
        return_value=station,
    ):
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        assert (
            hass.states.get("sensor.hurbanovo_sea_level_pressure").state
            == "unavailable"
        )
        assert hass.states.get("sensor.hurbanovo_pressure").state == "1001.2"


async def test_wind_bearing_is_averaged_as_an_angle(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """A plain ``measurement`` would average 350° and 10° to 180°, due south.

    ``measurement_angle`` makes long-term statistics take the circular mean.
    """
    await _setup(hass, entry, load)

    state = hass.states.get("sensor.hurbanovo_wind_bearing")
    assert state is not None
    assert state.attributes["device_class"] == "wind_direction"
    assert state.attributes["state_class"] == "measurement_angle"
    assert state.attributes["unit_of_measurement"] == "°"


async def test_snow_depth_is_a_distance(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """The device class is what lets a user display it in inches."""
    await _setup(hass, entry, load)

    state = hass.states.get("sensor.hurbanovo_snow_depth")
    assert state is not None
    assert state.attributes["device_class"] == "distance"
    assert state.attributes["unit_of_measurement"] == "cm"


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


async def test_upper_air_sensors_unavailable_without_the_fields(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """A run whose files carry no pressure levels must not invent a value."""
    await _setup_with_upper_air(
        hass, entry, load, freezing_level=None, temperature_850hpa=None
    )

    # The run is held, but the quantity is not in it.
    assert hass.states.get(_FREEZING_LEVEL).state == "unavailable"
    assert hass.states.get(_T850).state == "unavailable"


async def test_upper_air_sensors_unavailable_when_no_step_covers_now(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """A held run too stale to reach the present contributes nothing.

    Observations can keep succeeding while the forecast fetch fails, so the
    coordinator is healthy but its newest step is hours away from now — the
    same case in which the condition ladder stops consulting the model.
    """
    await _setup_with_upper_air(hass, entry, load, offset=timedelta(days=2))

    assert hass.states.get(_FREEZING_LEVEL).state == "unavailable"
    assert hass.states.get(_T850).state == "unavailable"


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
