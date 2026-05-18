"""Shared base entity for SHMÚ Weather."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import ShmuDataUpdateCoordinator
from .shmu_opendata import Observation, Station


class ShmuStationEntity(CoordinatorEntity[ShmuDataUpdateCoordinator]):
    """Base entity tying all platforms to one station's device."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ShmuDataUpdateCoordinator, station: Station
    ) -> None:
        """Initialise the entity for ``station``."""
        super().__init__(coordinator)
        self._station = station
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(station.ind_kli))},
            name=station.name,
            manufacturer=MANUFACTURER,
            model="Synoptic station",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=(
                f"https://www.shmu.sk/sk/?page=1&id=meteo_apocasie_sk"
                f"&ii={station.ind_kli}"
            ),
        )

    @property
    def observation(self) -> Observation | None:
        """The station's reading, carried forward across one-cycle dropouts."""
        return self.coordinator.observation

    @property
    def available(self) -> bool:
        """Available while the (possibly carried-forward) reading is fresh."""
        return super().available and self.observation is not None


class ShmuRadarEntity(ShmuStationEntity):
    """Base for entities backed by the *national* radar mosaic.

    Grouped under the configured station's device for tidiness, but the data
    is national: availability follows the held radar frame, **not** a fresh
    station observation (one station dropping out of a snapshot must not blank
    the radar). ``_unique_id_suffix`` distinguishes the radar entities on that
    one device.
    """

    _unique_id_suffix: str

    def __init__(
        self, coordinator: ShmuDataUpdateCoordinator, station: Station
    ) -> None:
        """Initialise and derive the per-entity unique id."""
        super().__init__(coordinator, station)
        self._attr_unique_id = f"{station.ind_kli}_{self._unique_id_suffix}"

    @property
    def available(self) -> bool:
        """Available while a radar frame is held — independent of the station."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.radar is not None
        )
