"""Weather platform for SHMÚ Weather."""

from __future__ import annotations

from homeassistant.components.weather import (
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_SUNNY,
    WeatherEntity,
)
from homeassistant.const import (
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.sun import is_up

from .const import CONF_IND_KLI
from .coordinator import ShmuConfigEntry, ShmuDataUpdateCoordinator
from .entity import ShmuStationEntity
from .shmu_opendata import get_station


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SHMÚ weather entity from a config entry."""
    coordinator = entry.runtime_data
    station = get_station(entry.data[CONF_IND_KLI])
    assert station is not None
    async_add_entities([ShmuWeather(coordinator, station)])


class ShmuWeather(ShmuStationEntity, WeatherEntity):
    """Current conditions for a SHMÚ synoptic station.

    Measurements come from the open-data feed; the qualitative ``condition``
    comes from the SHMÚ website (cloud + present weather), falling back to the
    ``stav_poc`` present-weather code when the website has nothing for this
    station. Forecast support arrives in Phase 2 (ALADIN model).
    """

    _attr_name = None  # the device name is the station; this is its weather
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_visibility_unit = UnitOfLength.METERS

    def __init__(self, coordinator: ShmuDataUpdateCoordinator, station) -> None:
        """Initialise the weather entity."""
        super().__init__(coordinator, station)
        self._attr_unique_id = f"{station.ind_kli}"

    @property
    def condition(self) -> str | None:
        """HA condition: website first, then ``stav_poc``, else unknown."""
        condition, _ = self.coordinator.data.resolve_condition(self._station)
        if condition == ATTR_CONDITION_SUNNY and not is_up(self.hass):
            return ATTR_CONDITION_CLEAR_NIGHT
        return condition

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Provenance, so unexpected readings are debuggable from the UI."""
        condition, source = self.coordinator.data.resolve_condition(self._station)
        obs = self.observation
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
