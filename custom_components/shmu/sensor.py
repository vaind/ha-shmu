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

from .coordinator import ShmuConfigEntry, ShmuData
from .entity import ShmuStationEntity
from .shmu_opendata import Observation

#: All entities read a single shared coordinator snapshot; there is no
#: per-entity device I/O to rate-limit, so updates need not be serialised.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ShmuSensorDescription(SensorEntityDescription):
    """Describes a SHMÚ sensor and how to read it from an observation."""

    value_fn: Callable[[Observation], StateType]


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
        ShmuTimestampSensor(coordinator, station, description)
        for description in TIMESTAMPS
    )
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
        warnings = self.coordinator.data.active_warnings_for(self._station)
        for level in ("red", "orange", "yellow", "green"):
            if any((w.awareness_level or "").lower() == level for w in warnings):
                return level
        return "none"
