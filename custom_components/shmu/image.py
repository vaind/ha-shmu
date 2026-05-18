"""Image platform for SHMÚ Weather: the national radar composite.

Two image entities, both rendered from the ODIM_H5 open data by the vendored
library (no binary deps, no scraping): the **latest** column-maximum
reflectivity frame, and an animated **loop** of the recent frames so the
precipitation's movement is visible at a glance. Both are grouped under the
configured station's device but are national data, so — unlike the
measurement entities — they stay available even when that station drops out
of an observation snapshot.
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
    """Set up the SHMÚ radar image entities from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        [ShmuRadarImage(hass, coordinator), ShmuRadarLoopImage(hass, coordinator)]
    )


class _ShmuRadarImageBase(ShmuStationEntity, ImageEntity):
    """Shared device wiring and national-data availability for the radar
    images.

    Reuses :class:`ShmuStationEntity` for the station device (so the
    ``configuration_url`` and device metadata stay in one place) and layers
    in :class:`ImageEntity`'s machinery. Subclasses set the translation key,
    the unique-id suffix and what bytes to serve.
    """

    _attr_content_type = "image/png"
    #: Distinguishes the entities under one station device.
    _unique_id_suffix: str

    def __init__(
        self, hass: HomeAssistant, coordinator: ShmuDataUpdateCoordinator
    ) -> None:
        """Initialise the radar image entity."""
        ShmuStationEntity.__init__(self, coordinator, coordinator.station)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"{coordinator.station.ind_kli}_{self._unique_id_suffix}"

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
        """Nominal UTC time of the newest held frame (drives frontend
        refresh)."""
        radar = self.coordinator.data.radar
        return None if radar is None else radar.valid_at


class ShmuRadarImage(_ShmuRadarImageBase):
    """The latest SHMÚ radar reflectivity composite as a PNG image."""

    _attr_translation_key = "radar"
    _unique_id_suffix = "radar"

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
            "center_latitude": img.center_lat,
            "center_longitude": img.center_lon,
            "bbox_south": img.south,
            "bbox_west": img.west,
            "bbox_north": img.north,
            "bbox_east": img.east,
        }

    async def async_image(self) -> bytes | None:
        """Return the rendered PNG, or ``None`` if no frame is held."""
        radar = self.coordinator.data.radar
        return None if radar is None else radar.image.png


class ShmuRadarLoopImage(_ShmuRadarImageBase):
    """The recent SHMÚ radar frames as an animated PNG loop.

    Same crop, palette and overlays as :class:`ShmuRadarImage`, but the last
    :data:`RADAR_LOOP_FRAMES` composites spliced into one APNG so you can
    watch where the precipitation is heading.
    """

    _attr_translation_key = "radar_loop"
    _unique_id_suffix = "radar_loop"

    @property
    def extra_state_attributes(self) -> dict[str, str | float | None]:
        """Provenance, the loop's time span and its geographic extent."""
        radar = self.coordinator.data.radar
        if radar is None:
            return {}
        img = radar.image
        return {
            "product": radar.product,
            "frame_count": len(radar.frames),
            "loop_start": radar.frames[0].valid_at.isoformat(),
            "loop_end": radar.frames[-1].valid_at.isoformat(),
            "center_latitude": img.center_lat,
            "center_longitude": img.center_lon,
            "bbox_south": img.south,
            "bbox_west": img.west,
            "bbox_north": img.north,
            "bbox_east": img.east,
        }

    async def async_image(self) -> bytes | None:
        """Return the animated PNG loop, or ``None`` if no frame is held."""
        radar = self.coordinator.data.radar
        return None if radar is None else radar.loop_png
