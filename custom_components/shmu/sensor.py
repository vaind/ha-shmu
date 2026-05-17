"""Sensor platform for SHMÚ Weather.

Individual measurements as their own entities so they can be graphed, kept in
long-term statistics and used in automations independently of the weather card.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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

from .coordinator import ShmuConfigEntry
from .entity import ShmuStationEntity
from .shmu_opendata import Observation


@dataclass(frozen=True, kw_only=True)
class ShmuSensorDescription(SensorEntityDescription):
    """Describes a SHMÚ sensor and how to read it from an observation."""

    value_fn: Callable[[Observation], StateType]


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
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda o: o.ground_temperature,
    ),
    ShmuSensorDescription(
        key="global_radiation",
        translation_key="global_radiation",
        device_class=SensorDeviceClass.IRRADIANCE,
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda o: o.global_radiation,
    ),
    ShmuSensorDescription(
        key="weather_code",
        translation_key="weather_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda o: o.weather_code,
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
        """Available whenever the coordinator has data (independent of obs)."""
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> str:
        """Return the worst active awareness level, or ``"none"``."""
        warnings = self.coordinator.data.active_warnings_for(self._station)
        for level in ("red", "orange", "yellow", "green"):
            if any((w.awareness_level or "").lower() == level for w in warnings):
                return level
        return "none"
