"""Diagnostics for SHMÚ Weather.

Surfaced by the "Download diagnostics" button. It captures both *inputs*
(raw SHMÚ records, fetch provenance, coordinator health) and *derived
outputs* (the condition and which source produced it) so a bug report is
self-contained. SHMÚ data is public and no credentials are used, so nothing
needs redacting; the user's home coordinates are deliberately not included.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from . import shmu_opendata
from .const import POLL_INTERVAL_MINUTES
from .coordinator import ShmuConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ShmuConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    station = coordinator.station

    obs_snapshot = data.observations
    observation = obs_snapshot.observations.get(station.ind_kli)
    served = coordinator.observation  # carried-forward reading entities see

    web = data.web_conditions
    web_condition = web.conditions.get(station.ind_kli) if web is not None else None

    forecast = data.forecast
    radar = data.radar

    # Shared resolver — exactly what the weather entity uses.
    condition, source = data.resolve_condition(station, served)

    return {
        "library_version": shmu_opendata.__version__,
        "station": {
            "ind_kli": station.ind_kli,
            "name": station.name,
            "latitude": station.latitude,
            "longitude": station.longitude,
            "elevation": station.elevation,
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_update": coordinator.last_success_at.isoformat()
            if coordinator.last_success_at
            else None,
            "next_update": coordinator.next_refresh_at.isoformat()
            if coordinator.next_refresh_at
            else None,
            "failures_since_success": coordinator.failures_since_success,
            "poll": f"UTC */{POLL_INTERVAL_MINUTES}min, auto-tuned offset",
            "last_exception": repr(coordinator.last_exception)
            if coordinator.last_exception
            else None,
        },
        "derived_condition": {"condition": condition, "source": source},
        "observations": {
            "source": obs_snapshot.source,
            "fetched_at": obs_snapshot.fetched_at.isoformat(),
            "station_count": len(obs_snapshot.observations),
            "station_present": observation is not None,
            # Full original SHMÚ row — invaluable for "why is sensor X null".
            "raw_record": dict(observation.raw) if observation else None,
        },
        "web_conditions": None
        if web is None
        else {
            "fetched_at": web.fetched_at.isoformat(),
            "station_count": len(web.conditions),
            "station": None
            if web_condition is None
            else {
                "cloud_text": web_condition.cloud_text,
                "weather_text": web_condition.weather_text,
                "condition": web_condition.condition,
            },
        },
        "forecast": None
        if forecast is None
        else {
            "source": forecast.source,
            "run": forecast.run.isoformat(),
            "fetched_at": forecast.fetched_at.isoformat(),
            "grid_point": list(forecast.grid_point),
            "step_count": len(forecast.steps),
            "first_step": (
                forecast.steps[0].time.isoformat() if forecast.steps else None
            ),
            "last_step": (
                forecast.steps[-1].time.isoformat() if forecast.steps else None
            ),
        },
        "radar": None
        if radar is None
        else {
            "source": radar.source,
            "product": radar.product,
            "valid_at": radar.valid_at.isoformat(),
            "fetched_at": radar.fetched_at.isoformat(),
            "loop_frames": len(radar.frames),
            "loop_start": radar.frames[0].valid_at.isoformat(),
            "loop_end": radar.frames[-1].valid_at.isoformat(),
            "size": [radar.image.width, radar.image.height],
            "max_dbz": radar.image.max_dbz,
            "center": [radar.image.center_lat, radar.image.center_lon],
            "bbox": [
                radar.image.south,
                radar.image.west,
                radar.image.north,
                radar.image.east,
            ],
        },
        "warnings": None
        if data.warnings is None
        else {
            "source": data.warnings.source,
            "fetched_at": data.warnings.fetched_at.isoformat(),
            "total_parsed": len(data.warnings.warnings),
            "active_for_station": [
                {
                    "event": w.event,
                    "severity": w.severity,
                    "awareness_level": w.awareness_level,
                    "awareness_type": w.awareness_type,
                    "onset": w.onset.isoformat() if w.onset else None,
                    "expires": w.expires.isoformat() if w.expires else None,
                    "areas": list(w.areas),
                }
                for w in data.active_warnings_for(station)
            ],
        },
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ShmuConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for the station device.

    Each config entry owns exactly one device (its station), so the
    device-scoped dump is the config-entry dump — exposing the same
    "Download diagnostics" button from the device page.
    """
    return await async_get_config_entry_diagnostics(hass, entry)
