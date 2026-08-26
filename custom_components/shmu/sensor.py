"""Sensor platform for SHMÚ Weather.

Individual measurements as their own entities so they can be graphed, kept in
long-term statistics and used in automations independently of the weather card.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    UnitOfIrradiance,
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .coordinator import ShmuConfigEntry, ShmuData
from .entity import ShmuStationEntity
from .shmu_opendata import ForecastStep, Observation, sea_level_pressure

#: All entities read a single shared coordinator snapshot; there is no
#: per-entity device I/O to rate-limit, so updates need not be serialised.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ShmuSensorDescription(SensorEntityDescription):
    """Describes a SHMÚ sensor and how to read it from an observation."""

    value_fn: Callable[[Observation], StateType]


@dataclass(frozen=True, kw_only=True)
class ShmuForecastSensorDescription(SensorEntityDescription):
    """Describes a quantity read from the ALADIN step standing in for now.

    Everything else on this platform is a *measurement* from the station; these
    come from the model run at the configured measurement location — the same
    "current step" the condition ladder already uses as its sky-state
    gap-filler.
    """

    value_fn: Callable[[ForecastStep], StateType]


@dataclass(frozen=True, kw_only=True)
class ShmuTimestampDescription(SensorEntityDescription):
    """A diagnostic timestamp describing freshness of a dataset in use.

    Reads from the whole coordinator snapshot rather than one station's
    observation, because the timestamps describe the SHMÚ *dataset* (when it
    was released and when we fetched it), not a measured value.
    """

    value_fn: Callable[[ShmuData], datetime | None]


SENSORS: tuple[ShmuSensorDescription, ...] = (
    ShmuSensorDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda o: o.temperature,
    ),
    ShmuSensorDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda o: o.humidity,
    ),
    # Raw station-level pressure (QFE) exactly as SHMÚ reports it. Sea-level
    # (QFF) pressure is a separate entity, ``ShmuSeaLevelPressureSensor``.
    ShmuSensorDescription(
        key="pressure",
        translation_key="pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda o: o.pressure,
    ),
    ShmuSensorDescription(
        key="wind_speed",
        translation_key="wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda o: o.wind_speed,
    ),
    ShmuSensorDescription(
        key="wind_gust",
        translation_key="wind_gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda o: o.wind_gust,
    ),
    ShmuSensorDescription(
        key="wind_bearing",
        translation_key="wind_bearing",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda o: o.wind_bearing,
    ),
    ShmuSensorDescription(
        key="precipitation",
        translation_key="precipitation",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda o: o.precipitation,
    ),
    ShmuSensorDescription(
        key="snow_depth",
        translation_key="snow_depth",
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda o: o.snow_depth,
    ),
    ShmuSensorDescription(
        key="visibility",
        translation_key="visibility",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda o: o.visibility,
    ),
    ShmuSensorDescription(
        key="ground_temperature",
        translation_key="ground_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda o: o.ground_temperature,
    ),
    ShmuSensorDescription(
        key="global_radiation",
        translation_key="global_radiation",
        device_class=SensorDeviceClass.IRRADIANCE,
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda o: o.global_radiation,
    ),
    # The raw WMO 4680 code is not a user-facing measurement — keep it as an
    # opt-in diagnostic for debugging the condition mapping.
    ShmuSensorDescription(
        key="weather_code",
        translation_key="weather_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda o: o.weather_code,
    ),
)


#: Upper-air quantities the ALADIN files have always carried (issue #44): the
#: hour-files hold temperature and geopotential on five pressure levels, and
#: every message is decoded whether or not we read it, so these cost nothing to
#: surface. They are **opt-in**: unlike the station measurements they are model
#: output, and most households will never look at them — an entity nobody reads
#: is permanent clutter, while enabling one is a single click.
FORECAST_SENSORS: tuple[ShmuForecastSensorDescription, ...] = (
    # Height of the 0 °C isotherm above sea level. It *indicates* the snow line
    # rather than being it — snow keeps falling and melting below the isotherm,
    # so the snow settles some way under it — but in a country where valley and
    # ridge differ by two kilometres, that indication is the point.
    ShmuForecastSensorDescription(
        key="freezing_level",
        translation_key="freezing_level",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        # Derived by interpolating a profile, so full float precision is noise;
        # the feed-backed sensors inherit SHMÚ's own rounding instead.
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.freezing_level,
    ),
    # The standard air-mass indicator: ~1450 m, above the boundary layer, so it
    # answers "is warmer/colder air moving in" far better than a 2 m reading.
    ShmuForecastSensorDescription(
        key="temperature_850hpa",
        translation_key="temperature_850hpa",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.temperature_850hpa,
    ),
)


#: Dataset-freshness diagnostics. ``observations`` is always present once the
#: coordinator has data; ``forecast`` may be absent (no published ALADIN run),
#: so its readers guard for ``None``. For the forecast the natural "released"
#: timestamp is the model run's reference time — the identity of the dataset
#: version in use — not a file ``Last-Modified``.
TIMESTAMPS: tuple[ShmuTimestampDescription, ...] = (
    ShmuTimestampDescription(
        key="observation_released",
        translation_key="observation_released",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.observations.published_at,
    ),
    ShmuTimestampDescription(
        key="observation_fetched",
        translation_key="observation_fetched",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.observations.fetched_at,
    ),
    ShmuTimestampDescription(
        key="forecast_run",
        translation_key="forecast_run",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.forecast.run if d.forecast else None,
    ),
    ShmuTimestampDescription(
        key="forecast_fetched",
        translation_key="forecast_fetched",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.forecast.fetched_at if d.forecast else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up SHMÚ sensors from a config entry."""
    coordinator = entry.runtime_data
    station = coordinator.station
    entities: list[SensorEntity] = [
        ShmuSensor(coordinator, station, description) for description in SENSORS
    ]
    entities.extend(
        ShmuForecastSensor(coordinator, station, description)
        for description in FORECAST_SENSORS
    )
    entities.extend(
        ShmuTimestampSensor(coordinator, station, description)
        for description in TIMESTAMPS
    )
    entities.append(ShmuSeaLevelPressureSensor(coordinator, station))
    entities.append(ShmuRainGaugePrecipitationSensor(coordinator, station))
    entities.append(ShmuWarningLevelSensor(coordinator, station))
    async_add_entities(entities)


class ShmuSensor(ShmuStationEntity, SensorEntity):
    """A single measured quantity from a SHMÚ station."""

    entity_description: ShmuSensorDescription

    def __init__(
        self, coordinator, station, description: ShmuSensorDescription
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, station)
        self.entity_description = description
        self._attr_unique_id = f"{station.ind_kli}_{description.key}"

    @property
    def native_value(self) -> StateType:
        """Return the current value, or ``None`` if the station omits it."""
        obs = self.observation
        if obs is None:
            return None
        return self.entity_description.value_fn(obs)


class ShmuSeaLevelPressureSensor(ShmuStationEntity, SensorEntity):
    """Station pressure reduced to mean sea level (QFF).

    SHMÚ's ``tlak`` is the raw barometer reading at the station (QFE), so it
    is not comparable between stations at different heights (a mountain station
    reads far below 1013 hPa). This entity reduces it to sea level using the
    station elevation and its current temperature, matching the datum of the
    forecast pressure and of most other weather sources.
    """

    _attr_translation_key = "pressure_sea_level"
    _attr_device_class = SensorDeviceClass.ATMOSPHERIC_PRESSURE
    _attr_native_unit_of_measurement = UnitOfPressure.HPA
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, station) -> None:
        """Initialise the sea-level pressure sensor."""
        super().__init__(coordinator, station)
        self._attr_unique_id = f"{station.ind_kli}_pressure_sea_level"

    @property
    def native_value(self) -> StateType:
        """Sea-level pressure, or ``None`` if pressure or temperature is absent."""
        obs = self.observation
        if obs is None:
            return None
        return sea_level_pressure(
            obs.pressure, self._station.elevation, obs.temperature
        )


class ShmuRainGaugePrecipitationSensor(ShmuStationEntity, SensorEntity):
    """Precipitation from the rain gauge nearest the measurement location.

    SHMÚ runs a second, ~3x denser observation network beside the synoptic
    stations (see :mod:`shmu_opendata.gauges`), so this usually measures rain
    much closer to the user than the station's own ``precipitation`` sensor —
    which is left untouched, because silently swapping one network's reading
    for another's under the same name would be exactly the wrong surprise.
    The two are expected to differ; the attributes say which gauge fed this.

    The gauge is chosen from the *measurement location* (as the forecast and
    radar are), not the station, and is fixed for the life of the entry.

    The unique id keys on the **station**, not the gauge, so changing the
    measurement location keeps this entity and its history rather than
    orphaning it and starting afresh. The cost is that such a history is
    *mixed*: long-term statistics keep only the aggregated value per period,
    never the attributes, so a series spanning a location change holds
    readings from two gauges with nothing recorded to say which fed when. The
    attributes describe the gauge in use **now**, not the history. Keying on
    the gauge would make the boundary explicit, but at the price of discarding
    the history every time the location moves — the worse trade for a sensor
    whose whole premise is "the gauge nearest wherever I am".
    """

    _attr_translation_key = "rain_gauge_precipitation"
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, station) -> None:
        """Initialise the rain-gauge precipitation sensor."""
        super().__init__(coordinator, station)
        self._attr_unique_id = f"{station.ind_kli}_rain_gauge_precipitation"
        gauge = coordinator.gauge
        self._attr_extra_state_attributes = {
            "gauge_ind_zra": gauge.ind_zra,
            "gauge_name": gauge.name,
            "gauge_distance_km": round(
                gauge.distance_km(
                    coordinator.location_latitude, coordinator.location_longitude
                ),
                1,
            ),
        }

    @property
    def available(self) -> bool:
        """Follows the *gauge's* reading, not the station's.

        The two networks are independent: the station dropping out of a
        snapshot says nothing about the gauge, and vice versa. Overrides
        :attr:`ShmuStationEntity.available`, which gates on the station.
        """
        return self.coordinator.gauge_observation is not None

    @property
    def native_value(self) -> StateType:
        """The gauge's 1-minute precipitation sum, or ``None``."""
        obs = self.coordinator.gauge_observation
        if obs is None:
            return None
        return obs.precipitation


class ShmuForecastSensor(ShmuStationEntity, SensorEntity):
    """A model quantity for the present hour, from the ALADIN forecast.

    Availability follows the coordinator's recent success rather than a fresh
    station reading: this is national model data for the measurement location,
    so a station dropping out of one observation snapshot says nothing about
    it. The value is ``None`` — surfaced as ``unknown`` — while no run covers
    the present, the same way the condition ladder simply stops using the model
    then.
    """

    entity_description: ShmuForecastSensorDescription

    def __init__(
        self, coordinator, station, description: ShmuForecastSensorDescription
    ) -> None:
        """Initialise the forecast-derived sensor."""
        super().__init__(coordinator, station)
        self.entity_description = description
        self._attr_unique_id = f"{station.ind_kli}_{description.key}"

    @property
    def available(self) -> bool:
        """Available while a recent successful fetch backs the held run."""
        return self.coordinator.has_recent_success

    @property
    def native_value(self) -> StateType:
        """Value at the current hour, or ``None`` if no step covers it."""
        step = self.coordinator.data.current_forecast_step(dt_util.utcnow())
        if step is None:
            return None
        return self.entity_description.value_fn(step)


class ShmuTimestampSensor(ShmuStationEntity, SensorEntity):
    """A diagnostic timestamp for when a dataset was released and fetched."""

    entity_description: ShmuTimestampDescription

    def __init__(
        self, coordinator, station, description: ShmuTimestampDescription
    ) -> None:
        """Initialise the timestamp diagnostic."""
        super().__init__(coordinator, station)
        self.entity_description = description
        self._attr_unique_id = f"{station.ind_kli}_{description.key}"

    @property
    def available(self) -> bool:
        """Stay available even when a station reading is stale.

        These timestamps describe dataset freshness, so they must remain
        visible precisely when data is going stale — unlike the measurement
        sensors, they are not gated on a fresh station observation. A ``None``
        value (e.g. no forecast run yet) is reported as ``unknown``.
        """
        return self.coordinator.data is not None

    @property
    def native_value(self) -> datetime | None:
        """Return the dataset timestamp, or ``None`` if unavailable."""
        return self.entity_description.value_fn(self.coordinator.data)


class ShmuWarningLevelSensor(ShmuStationEntity, SensorEntity):
    """Worst active CAP awareness level over the station (green→red)."""

    _attr_translation_key = "warning_level"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = ["none", "green", "yellow", "orange", "red"]

    def __init__(self, coordinator, station) -> None:
        """Initialise the warning-level sensor."""
        super().__init__(coordinator, station)
        self._attr_unique_id = f"{station.ind_kli}_warning_level"

    @property
    def available(self) -> bool:
        """Available while a recent successful fetch backs the cached warnings.

        Independent of the station's reading, but still gated on a recent
        coordinator success so a multi-cycle outage eventually surfaces.
        """
        return self.coordinator.has_recent_success

    @property
    def native_value(self) -> str:
        """Return the worst active awareness level, or ``"none"``."""
        warnings = self.coordinator.data.active_warnings_for(
            self.coordinator.location_latitude,
            self.coordinator.location_longitude,
        )
        for level in ("red", "orange", "yellow", "green"):
            if any((w.awareness_level or "").lower() == level for w in warnings):
                return level
        return "none"
