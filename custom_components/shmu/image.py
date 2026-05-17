"""Image platform for SHMÚ Weather: the national radar composite.

A single image entity showing SHMÚ's latest column-maximum reflectivity radar
mosaic, rendered from the ODIM_H5 open data by the vendored library (no
binary deps, no scraping). It is grouped under the configured station's device
but is national data, so — unlike the measurement entities — it stays
available even when that station drops out of an observation snapshot.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import ShmuConfigEntry, ShmuDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SHMÚ radar image entity from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities([ShmuRadarImage(hass, coordinator)])


class ShmuRadarImage(CoordinatorEntity[ShmuDataUpdateCoordinator], ImageEntity):
    """The latest SHMÚ radar reflectivity composite as a PNG image."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_translation_key = "radar"
    _attr_content_type = "image/png"

    def __init__(
        self, hass: HomeAssistant, coordinator: ShmuDataUpdateCoordinator
    ) -> None:
        """Initialise the radar image entity."""
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        station = coordinator.station
        self._attr_unique_id = f"{station.ind_kli}_radar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(station.ind_kli))},
            name=station.name,
            manufacturer=MANUFACTURER,
            model="Synoptic station",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        """Available whenever a radar frame is held (independent of station)."""
        return super().available and self.coordinator.data.radar is not None

    @property
    def image_last_updated(self) -> datetime | None:
        """Nominal UTC time of the held frame (drives frontend refresh)."""
        radar = self.coordinator.data.radar
        return None if radar is None else radar.valid_at

    @property
    def extra_state_attributes(self) -> dict[str, str | float | None]:
        """Provenance and the frame's geographic extent for map overlays."""
        radar = self.coordinator.data.radar
        if radar is None:
            return {}
        img = radar.image
        return {
            "product": radar.product,
            "source": radar.source,
            "max_dbz": img.max_dbz,
            "bbox_south": img.south,
            "bbox_west": img.west,
            "bbox_north": img.north,
            "bbox_east": img.east,
        }

    async def async_image(self) -> bytes | None:
        """Return the rendered PNG, or ``None`` if no frame is held."""
        radar = self.coordinator.data.radar
        return None if radar is None else radar.image.png
