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
from .entity import ShmuRadarEntity

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
        [
            ShmuRadarImage(hass, coordinator),
            ShmuRadarLoopImage(hass, coordinator),
            ShmuRadarFrameImage(hass, coordinator),
        ]
    )


class _ShmuRadarImageBase(ShmuRadarEntity, ImageEntity):
    """Shared device wiring for the radar image entities.

    :class:`ShmuRadarEntity` supplies the station device, the national-data
    availability and the unique id; this layers in :class:`ImageEntity`'s
    machinery. Subclasses set the translation key, the unique-id suffix and
    what bytes to serve.
    """

    _attr_content_type = "image/png"

    def __init__(
        self, hass: HomeAssistant, coordinator: ShmuDataUpdateCoordinator
    ) -> None:
        """Initialise the radar image entity."""
        ShmuRadarEntity.__init__(self, coordinator, coordinator.station)
        ImageEntity.__init__(self, hass)

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


class ShmuRadarFrameImage(_ShmuRadarImageBase):
    """A single buffered radar frame, chosen by the "Radar frame" number.

    Lets a dashboard slider scrub the loop manually: the companion number
    entity sets :attr:`ShmuDataUpdateCoordinator.radar_frame_offset` and this
    serves that frame. ``image_last_updated`` tracks the *selected* frame's
    time, so moving the slider (or new data arriving) re-fetches the picture.
    """

    _attr_translation_key = "radar_frame"
    _unique_id_suffix = "radar_frame"

    @property
    def image_last_updated(self) -> datetime | None:
        """The selected frame's time — changes on scrub *and* on new data."""
        frame = self.coordinator.selected_radar_frame()
        return None if frame is None else frame.valid_at

    @property
    def extra_state_attributes(self) -> dict[str, str | float | None]:
        """Which frame is shown plus the shared geographic extent."""
        radar = self.coordinator.data.radar
        frame = self.coordinator.selected_radar_frame()
        if radar is None or frame is None:
            return {}
        img = frame.image
        return {
            "product": radar.product,
            "frame_offset": self.coordinator.radar_frame_offset,
            "frame_count": len(radar.frames),
            "valid_at": frame.valid_at.isoformat(),
            "center_latitude": img.center_lat,
            "center_longitude": img.center_lon,
            "bbox_south": img.south,
            "bbox_west": img.west,
            "bbox_north": img.north,
            "bbox_east": img.east,
        }

    async def async_image(self) -> bytes | None:
        """Return the selected frame's PNG, or ``None`` if none is held."""
        frame = self.coordinator.selected_radar_frame()
        return None if frame is None else frame.image.png
