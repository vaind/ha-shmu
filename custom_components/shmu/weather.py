"""Weather platform for SHMÚ Weather."""

from __future__ import annotations

from datetime import date

from homeassistant.components.weather import (
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_SUNNY,
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.sun import is_up
from homeassistant.util import dt as dt_util

from .coordinator import ShmuConfigEntry, ShmuDataUpdateCoordinator
from .entity import ShmuStationEntity
from .shmu_opendata import ForecastStep

#: Worst-first ranking used to pick a single representative daily condition.
_CONDITION_SEVERITY = {
    "lightning-rainy": 7,
    "snowy": 6,
    "snowy-rainy": 5,
    "pouring": 4,
    "rainy": 3,
    "cloudy": 2,
    "partlycloudy": 1,
    "sunny": 0,
}
_PRECIP_CONDITIONS = {
    "lightning-rainy",
    "snowy",
    "snowy-rainy",
    "pouring",
    "rainy",
}


def _daily_condition(steps: list[ForecastStep]) -> str | None:
    """Most significant condition for a day.

    A day with any precipitation is summarised by its worst precipitation
    condition (a thunderstorm should not be hidden behind a "cloudy"
    average); an otherwise-dry day uses the sky state nearest local noon so
    the daily icon reflects daytime, not a clear night.
    """
    conditions = [s.condition for s in steps if s.condition is not None]
    if not conditions:
        return None
    precip = [c for c in conditions if c in _PRECIP_CONDITIONS]
    if precip:
        return max(precip, key=lambda c: _CONDITION_SEVERITY[c])
    noon_step = min(steps, key=lambda s: abs(dt_util.as_local(s.time).hour - 12))
    return noon_step.condition or max(
        conditions, key=lambda c: _CONDITION_SEVERITY.get(c, 0)
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SHMÚ weather entity from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities([ShmuWeather(coordinator, coordinator.station)])


class ShmuWeather(ShmuStationEntity, WeatherEntity):
    """Current conditions for a SHMÚ synoptic station.

    Measurements come from the open-data feed; the qualitative ``condition``
    comes from the SHMÚ website (cloud + present weather), falling back to the
    ``stav_poc`` present-weather code when the website has nothing for this
    station. The forecast comes from the ALADIN 4.5 km model decoded at the
    station's grid point; its ``condition`` is model-derived (cloud + precip),
    so the forecast path needs no scraping.
    """

    _attr_name = None  # the device name is the station; this is its weather
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_visibility_unit = UnitOfLength.METERS
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(self, coordinator: ShmuDataUpdateCoordinator, station) -> None:
        """Initialise the weather entity."""
        super().__init__(coordinator, station)
        self._attr_unique_id = f"{station.ind_kli}"

    @property
    def condition(self) -> str | None:
        """HA condition: website first, then ``stav_poc``, else unknown."""
        condition, _ = self.coordinator.data.resolve_condition(
            self._station, self.observation
        )
        if condition == ATTR_CONDITION_SUNNY and not is_up(self.hass):
            return ATTR_CONDITION_CLEAR_NIGHT
        return condition

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Provenance, so unexpected readings are debuggable from the UI."""
        obs = self.observation
        condition, source = self.coordinator.data.resolve_condition(self._station, obs)
        snapshot = self.coordinator.data.observations
        return {
            "station_id": str(self._station.ind_kli),
            "condition_source": source,
            "raw_condition": condition,
            "observation_time": (
                obs.measured_at.isoformat() if obs is not None else None
            ),
            "data_source": snapshot.source,
        }

    @property
    def native_temperature(self) -> float | None:
        return obs.temperature if (obs := self.observation) is not None else None

    @property
    def humidity(self) -> float | None:
        return obs.humidity if (obs := self.observation) is not None else None

    @property
    def native_pressure(self) -> float | None:
        return obs.pressure if (obs := self.observation) is not None else None

    @property
    def native_wind_speed(self) -> float | None:
        return obs.wind_speed if (obs := self.observation) is not None else None

    @property
    def native_wind_gust_speed(self) -> float | None:
        return obs.wind_gust if (obs := self.observation) is not None else None

    @property
    def wind_bearing(self) -> float | None:
        return obs.wind_bearing if (obs := self.observation) is not None else None

    @property
    def native_visibility(self) -> float | None:
        return obs.visibility if (obs := self.observation) is not None else None

    def _steps(self) -> list[ForecastStep]:
        """Forecast steps for the station, or empty if none are available."""
        snapshot = self.coordinator.data.forecast
        return snapshot.steps if snapshot is not None else []

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Per-hour ALADIN forecast at the station's grid point."""
        steps = self._steps()
        if not steps:
            return None
        return [
            Forecast(
                datetime=step.time.isoformat(),
                native_temperature=step.temperature,
                native_precipitation=step.precipitation,
                condition=step.condition,
                native_wind_speed=step.wind_speed,
                native_wind_gust_speed=step.wind_gust,
                wind_bearing=step.wind_bearing,
                native_pressure=step.pressure,
                cloud_coverage=(
                    None if step.cloud_coverage is None else round(step.cloud_coverage)
                ),
            )
            for step in steps
        ]

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """ALADIN forecast aggregated to local (Europe/Bratislava) days.

        The model is hourly; a daily entry summarises each calendar day in
        Home Assistant's configured timezone: temperature high/low, total
        precipitation, and the day's most significant condition.
        """
        steps = self._steps()
        if not steps:
            return None

        by_day: dict[date, list[ForecastStep]] = {}
        for step in steps:
            by_day.setdefault(dt_util.as_local(step.time).date(), []).append(step)

        daily: list[Forecast] = []
        for day, day_steps in sorted(by_day.items()):
            temps = [s.temperature for s in day_steps if s.temperature is not None]
            precs = [s.precipitation for s in day_steps if s.precipitation is not None]
            winds = [s.wind_speed for s in day_steps if s.wind_speed is not None]
            gusts = [s.wind_gust for s in day_steps if s.wind_gust is not None]
            clouds = [
                s.cloud_coverage for s in day_steps if s.cloud_coverage is not None
            ]
            daily.append(
                Forecast(
                    datetime=dt_util.start_of_local_day(day).isoformat(),
                    native_temperature=max(temps) if temps else None,
                    native_templow=min(temps) if temps else None,
                    native_precipitation=round(sum(precs), 2) if precs else None,
                    condition=_daily_condition(day_steps),
                    native_wind_speed=max(winds) if winds else None,
                    native_wind_gust_speed=max(gusts) if gusts else None,
                    cloud_coverage=(
                        round(sum(clouds) / len(clouds)) if clouds else None
                    ),
                )
            )
        return daily
