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

from . import shmu_opendata
from .const import CONF_IND_KLI
from .coordinator import ShmuConfigEntry
from .shmu_opendata import get_station


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ShmuConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    station = get_station(entry.data[CONF_IND_KLI])
    assert station is not None

    obs_snapshot = data.observations
    observation = obs_snapshot.observations.get(station.ind_kli)

    web = data.web_conditions
    web_condition = web.conditions.get(station.ind_kli) if web is not None else None

    # Shared resolver — same precedence the weather entity uses.
    condition, source = data.resolve_condition(station)

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
            "update_interval_s": coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None,
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
