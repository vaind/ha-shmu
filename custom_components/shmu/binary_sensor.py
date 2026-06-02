"""Binary sensor platform for SHMÚ Weather: active weather warnings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShmuConfigEntry
from .entity import ShmuStationEntity

#: All entities read a single shared coordinator snapshot; there is no
#: per-entity device I/O to rate-limit, so updates need not be serialised.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShmuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SHMÚ warning binary sensor from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities([ShmuWarningBinarySensor(coordinator, coordinator.station)])


class ShmuWarningBinarySensor(ShmuStationEntity, BinarySensorEntity):
    """On while a SHMÚ CAP warning is in force over this station."""

    _attr_translation_key = "weather_warning"
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, coordinator, station) -> None:
        """Initialise the warning binary sensor."""
        super().__init__(coordinator, station)
        self._attr_unique_id = f"{station.ind_kli}_weather_warning"

    @property
    def available(self) -> bool:
        """Available while a recent successful fetch backs the cached warnings.

        Independent of the station's reading, but still gated on a recent
        coordinator success so a multi-cycle outage eventually surfaces.
        """
        return self.coordinator.has_recent_success

    @property
    def is_on(self) -> bool:
        """Whether any active warning covers the measurement location."""
        return bool(
            self.coordinator.data.active_warnings_for(
                self.coordinator.location_latitude,
                self.coordinator.location_longitude,
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Details of the active warnings (worst severity first)."""
        warnings = self.coordinator.data.active_warnings_for(
            self.coordinator.location_latitude,
            self.coordinator.location_longitude,
        )
        return {
            "warning_count": len(warnings),
            "warnings": [
                {
                    "event": w.event,
                    "severity": w.severity,
                    "awareness_level": w.awareness_level,
                    "awareness_type": w.awareness_type,
                    "headline": w.headline,
                    "onset": w.onset.isoformat() if w.onset else None,
                    "expires": w.expires.isoformat() if w.expires else None,
                    "areas": list(w.areas),
                }
                for w in warnings
            ],
        }
