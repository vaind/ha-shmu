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
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShmuConfigEntry, ShmuDataUpdateCoordinator
from .entity import ShmuStationEntity

# Coordinator-only entity: all I/O is the shared coordinator's, none per
# entity. Matches the other SHMÚ platforms / the integration's
# `parallel-updates: done` convention.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SHMÚ radar image entity from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities([ShmuRadarImage(hass, coordinator)])


class ShmuRadarImage(ShmuStationEntity, ImageEntity):
    """The latest SHMÚ radar reflectivity composite as a PNG image."""

    _attr_translation_key = "radar"
    _attr_content_type = "image/png"

    def __init__(
        self, hass: HomeAssistant, coordinator: ShmuDataUpdateCoordinator
    ) -> None:
        """Initialise the radar image entity.

        Reuses :class:`ShmuStationEntity` for the station device (so the
        ``configuration_url`` and device metadata stay in one place) and
        layers in :class:`ImageEntity`'s machinery.
        """
        ShmuStationEntity.__init__(self, coordinator, coordinator.station)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"{coordinator.station.ind_kli}_radar"

    @property
    def available(self) -> bool:
        """Available while a radar frame is held — independent of the station.

        Deliberately *not* ``ShmuStationEntity.available`` (which gates on a
        fresh station observation): the radar mosaic is national data and
        must survive a single station dropping out of an observation snapshot.
        """
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.radar is not None
        )

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
