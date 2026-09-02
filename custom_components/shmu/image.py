"""Image platform for SHMÚ Weather: the national radar composite.

Every entity here is rendered from the ODIM_H5 open data by the vendored
library (no binary deps, no scraping), and comes in two flavours of the same
three pictures — the **latest** column-maximum reflectivity frame, an animated
**loop** of the recent frames, and a single **buffered frame** picked by the
"Radar frame" number:

- the *picture-card* set (``radar``, ``radar_loop``, ``radar_frame``) is
  cropped to the station, with borders, a station marker and a timestamp drawn
  on, so it stands alone in any plain Lovelace card;
- the *map-overlay* set (``radar_map``, ``radar_map_loop``,
  ``radar_map_frame``) is the whole country at the radar's native resolution
  with nothing drawn on it, to be draped over a map card that supplies the
  basemap and the zoom (see the bundled ha-map-card plugin).

All of them are grouped under the configured station's device but are national
data, so — unlike the measurement entities — they stay available even when that
station drops out of an observation snapshot.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShmuConfigEntry, ShmuDataUpdateCoordinator
from .entity import ShmuRadarEntity
from .shmu_opendata import RadarFrame, RadarImage, RadarSnapshot

# Coordinator-only entity: all I/O is the shared coordinator's, none per
# entity. Matches the other SHMÚ platforms / the integration's
# `parallel-updates: done` convention.
PARALLEL_UPDATES = 0


def _geo_extent(img: RadarImage) -> dict[str, float]:
    """The frame's centre + WGS84 bounding box, for map-overlay attributes.

    Shared by every radar image entity so the attribute keys/values can never
    drift between the still, loop and scrubbed-frame pictures. The box is the
    one that picture actually covers, so it differs between the two renderings
    (a station crop against the whole national grid) — which is exactly what a
    map overlay must be positioned by.
    """
    return {
        "center_latitude": img.center_lat,
        "center_longitude": img.center_lon,
        "bbox_south": img.south,
        "bbox_west": img.west,
        "bbox_north": img.north,
        "bbox_east": img.east,
    }


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
            ShmuRadarMapImage(hass, coordinator),
            ShmuRadarMapLoopImage(hass, coordinator),
            ShmuRadarMapFrameImage(hass, coordinator),
        ]
    )


class _ShmuRadarImageBase(ShmuRadarEntity, ImageEntity):
    """Shared device wiring for the radar image entities.

    :class:`ShmuRadarEntity` supplies the station device, the national-data
    availability and the unique id; this layers in :class:`ImageEntity`'s
    machinery. Subclasses set the translation key, the unique-id suffix and
    what bytes to serve.

    ``_map`` selects which of the two renderings the coordinator holds this
    entity serves. Device, availability, timestamps and attributes are
    identical either way, so each map entity is its picture-card counterpart
    with the flag flipped.
    """

    _attr_content_type = "image/png"
    #: Serve the undecorated, full-coverage map overlay instead of the
    #: station-centred picture.
    _map = False

    def __init__(
        self, hass: HomeAssistant, coordinator: ShmuDataUpdateCoordinator
    ) -> None:
        """Initialise the radar image entity."""
        ShmuRadarEntity.__init__(self, coordinator, coordinator.station)
        ImageEntity.__init__(self, hass)

    def _still(self, radar: RadarSnapshot) -> RadarImage:
        """The newest frame, in this entity's rendering."""
        return radar.map_image if self._map else radar.image

    def _frame(self, frame: RadarFrame) -> RadarImage:
        """One buffered frame, in this entity's rendering."""
        return frame.map_image if self._map else frame.image

    def _loop(self, radar: RadarSnapshot) -> bytes:
        """The animated loop, in this entity's rendering."""
        return radar.map_loop_png if self._map else radar.loop_png

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
        img = self._still(radar)
        return {
            "product": radar.product,
            "source": radar.source,
            "max_dbz": img.max_dbz,
            **_geo_extent(img),
        }

    async def async_image(self) -> bytes | None:
        """Return the rendered PNG, or ``None`` if no frame is held."""
        radar = self.coordinator.data.radar
        return None if radar is None else self._still(radar).png


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
        return {
            "product": radar.product,
            "frame_count": len(radar.frames),
            "loop_start": radar.frames[0].valid_at.isoformat(),
            "loop_end": radar.frames[-1].valid_at.isoformat(),
            **_geo_extent(self._still(radar)),
        }

    async def async_image(self) -> bytes | None:
        """Return the animated PNG loop, or ``None`` if no frame is held."""
        radar = self.coordinator.data.radar
        return None if radar is None else self._loop(radar)


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
        return {
            "product": radar.product,
            "frame_offset": self.coordinator.radar_frame_offset,
            "frame_count": len(radar.frames),
            "valid_at": frame.valid_at.isoformat(),
            **_geo_extent(self._frame(frame)),
        }

    async def async_image(self) -> bytes | None:
        """Return the selected frame's PNG, or ``None`` if none is held."""
        frame = self.coordinator.selected_radar_frame()
        return None if frame is None else self._frame(frame).png


class ShmuRadarMapImage(ShmuRadarImage):
    """:class:`ShmuRadarImage` rendered to drape over a map card.

    The whole national grid at the radar's native ~0.3 km resolution, nothing
    drawn on it, transparent where there is no echo. ``bbox_*`` is then the
    composite's own corner coordinates, so a Leaflet ``imageOverlay`` placed
    between them lands exactly on the ground. ``max_dbz`` is the strongest
    echo **anywhere in the country**, not near the station.
    """

    _attr_translation_key = "radar_map"
    _unique_id_suffix = "radar_map"
    _map = True


class ShmuRadarMapLoopImage(ShmuRadarLoopImage):
    """:class:`ShmuRadarLoopImage` rendered to drape over a map card.

    Carries no step markers, for the same reason it carries no timestamp: a
    map overlay is drawn in ground coordinates, so anything baked into a
    corner of the picture ends up somewhere in the terrain, at whatever size
    the current zoom implies.
    """

    _attr_translation_key = "radar_map_loop"
    _unique_id_suffix = "radar_map_loop"
    _map = True


class ShmuRadarMapFrameImage(ShmuRadarFrameImage):
    """:class:`ShmuRadarFrameImage` rendered to drape over a map card.

    Pairs the existing scrubber with a zoomable map: the "Radar frame" slider
    still picks the frame, this serves it in map form.
    """

    _attr_translation_key = "radar_map_frame"
    _unique_id_suffix = "radar_map_frame"
    _map = True
