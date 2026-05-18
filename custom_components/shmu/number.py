"""Number platform for SHMÚ Weather: the radar loop scrubber.

A single :class:`homeassistant.components.number.NumberEntity` rendered as a
slider. It does not store anything itself — it writes the chosen position to
the shared coordinator (:attr:`ShmuDataUpdateCoordinator.radar_frame_offset`)
and the ``image.*_radar_frame`` entity serves that frame. So a plain
``input_number``/slider card scrubs the loop with no custom frontend code:
the integration just exposes the buffer we already keep.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShmuConfigEntry, ShmuDataUpdateCoordinator
from .entity import ShmuRadarEntity

# Coordinator-only entity: no per-entity I/O. Matches the other SHMÚ
# platforms / the integration's `parallel-updates: done` convention.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SHMÚ radar-frame scrubber from a config entry."""
    async_add_entities([ShmuRadarFrameNumber(entry.runtime_data)])


class ShmuRadarFrameNumber(ShmuRadarEntity, NumberEntity):
    """Slider selecting how many frames back from live the radar shows.

    ``0`` is the latest frame (so the default matches the still image and
    stays meaningful as the buffer rotates); the maximum tracks the number of
    buffered frames so the slider spans exactly what is available.
    """

    _attr_translation_key = "radar_frame"
    _unique_id_suffix = "radar_frame"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0
    _attr_native_step = 1

    def __init__(self, coordinator: ShmuDataUpdateCoordinator) -> None:
        """Initialise the scrubber for the coordinator's station."""
        ShmuRadarEntity.__init__(self, coordinator, coordinator.station)

    def _frame_count(self) -> int:
        radar = self.coordinator.data.radar
        return 0 if radar is None else len(radar.frames)

    @property
    def native_max_value(self) -> float:
        """Oldest selectable offset = buffered frame count minus one."""
        return float(max(0, self._frame_count() - 1))

    @property
    def native_value(self) -> float | None:
        """The current offset, clamped to what the buffer currently holds."""
        if self._frame_count() == 0:
            return None
        return float(
            max(0, min(self.coordinator.radar_frame_offset, self._frame_count() - 1))
        )

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        """The selected frame's time + buffer size, for slider cards."""
        frame = self.coordinator.selected_radar_frame()
        return {
            "frame_count": self._frame_count(),
            "selected_valid_at": None if frame is None else frame.valid_at.isoformat(),
        }

    async def async_set_native_value(self, value: float) -> None:
        """Move the scrubber and re-render the selectable-frame image.

        Notifying the coordinator's listeners is what makes the
        ``radar_frame`` image refetch: its ``image_last_updated`` follows the
        newly selected frame.
        """
        count = self._frame_count()
        self.coordinator.radar_frame_offset = max(
            0, min(int(value), count - 1 if count else 0)
        )
        self.coordinator.async_update_listeners()
