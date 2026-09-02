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
from homeassistant.util import dt as dt_util

from . import shmu_opendata
from .const import POLL_INTERVAL_MINUTES
from .coordinator import ShmuConfigEntry

#: Coordinates derived from the measurement location (the radar crop) are
#: coarsened to ~0.1° (~11 km) in diagnostics so the dump can never pinpoint a
#: user's private home/custom point, while still showing roughly where the crop
#: sits (see the module docstring's no-home-coordinates rule).
_COORD_PRECISION = 1


def _coarse(value: float) -> float:
    """Round a coordinate to grid-scale precision for privacy."""
    return round(value, _COORD_PRECISION)


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

    gauge = coordinator.gauge
    gauge_snapshot = data.gauge_observations
    gauge_record = (
        gauge_snapshot.observations.get(gauge.ind_zra)
        if gauge_snapshot is not None
        else None
    )
    gauge_served = coordinator.gauge_observation  # what the sensor shows

    # Shared resolver — exactly what the weather entity uses, but the full
    # evaluation (every candidate + which won) so a dump explains the result.
    resolution = data.explain_condition(station, served)
    current_step = data.current_forecast_step(dt_util.utcnow())

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
            # Mode only — never the resolved home/custom coordinates, which are
            # the user's private location (see module docstring).
            "location_mode": coordinator.location_mode,
            "poll": f"UTC */{POLL_INTERVAL_MINUTES}min, auto-tuned offset",
            "last_exception": repr(coordinator.last_exception)
            if coordinator.last_exception
            else None,
        },
        "derived_condition": {
            "condition": resolution.condition,
            "source": resolution.source,
            # Every source that produced a reading, highest priority first; the
            # winner (== condition/source above) is flagged.
            "candidates": [
                {
                    "source": c.source,
                    "tier": c.tier,
                    "priority": c.priority,
                    "condition": c.condition,
                    "won": index == 0,
                }
                for index, c in enumerate(resolution.candidates)
            ],
            # ``active`` when a station's "no significant weather" observation
            # vetoed the model's precipitation/storm candidate.
            "veto": {
                "active": resolution.suppressed_model_condition is not None,
                "suppressed_model_condition": resolution.suppressed_model_condition,
            },
        },
        "observations": {
            "source": obs_snapshot.source,
            "fetched_at": obs_snapshot.fetched_at.isoformat(),
            "station_count": len(obs_snapshot.observations),
            "station_present": observation is not None,
            # Full original SHMÚ row — invaluable for "why is sensor X null".
            "raw_record": dict(observation.raw) if observation else None,
        },
        # The gauge is identified but its *distance* is deliberately not
        # reported, and neither are its coordinates. Naming the gauge is
        # harmless on its own — it narrows the measurement location no further
        # than the ~0.1° radar box below already does, since this network's
        # per-gauge cell is the larger of the two. A distance is different in
        # kind: combined with the gauge's public coordinates it places the
        # location on a narrow ring, and intersecting that ring with the radar
        # box would pin it down roughly a hundred times more tightly than
        # either value alone — defeating the coarsening that the module
        # docstring's no-home-coordinates rule depends on. The sensor's own
        # attributes still carry the exact distance; they stay on the user's
        # instance rather than going into a shareable dump.
        "rain_gauge": {
            "ind_zra": gauge.ind_zra,
            "name": gauge.name,
            "source": gauge_snapshot.source if gauge_snapshot else None,
            "fetched_at": gauge_snapshot.fetched_at.isoformat()
            if gauge_snapshot
            else None,
            "gauge_count": len(gauge_snapshot.observations) if gauge_snapshot else None,
            "gauge_present": gauge_record is not None,
            # False while a carried-forward reading is still being served.
            "reading_stale": gauge_served is None,
            "raw_record": dict(gauge_record.raw) if gauge_record else None,
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
            # First and last decoded forecast hour of the newest run — named a
            # range, not ``forecast_hours``, because the snapshot's field of
            # that name is the full hour tuple and the two must not be read as
            # the same thing. The endpoints bound the run's reach; they do not
            # imply every hour between is present (the requested set is hourly
            # only to +48 h, 3-hourly beyond) — what the client guarantees is
            # that no *requested* hour inside the range is missing.
            "forecast_hour_range": [
                forecast.forecast_hours[0],
                forecast.forecast_hours[-1],
            ]
            if forecast.forecast_hours
            else None,
            "fetched_at": forecast.fetched_at.isoformat(),
            "grid_point": list(forecast.grid_point),
            "step_count": len(forecast.steps),
            # Which runs the series is actually built from, newest last. More
            # than one is the normal merged case. A sole entry equal to ``run``
            # means nothing was merged in — either the first fetch after a
            # restart, or the merge opted out because the steps stopped tiling
            # (see ``coordinator._merge_forecast_runs``); only its warning log
            # tells the two apart. An entry *older* than ``run`` is a carried
            # tail, which is normal — but one lagging by more than a day is a
            # tail left behind by a failing fetch, visible here and nowhere
            # else.
            "contributing_runs": sorted(
                {step.run.isoformat() for step in forecast.steps}
            ),
            "first_step": (
                forecast.steps[0].time.isoformat() if forecast.steps else None
            ),
            "last_step": (
                forecast.steps[-1].time.isoformat() if forecast.steps else None
            ),
            # The step standing in for "now" — the model reading the ladder saw
            # (``None`` if the run is too stale to cover the present).
            "current_step": None
            if current_step is None
            else {
                "time": current_step.time.isoformat(),
                "condition": current_step.condition,
                "cloud_coverage": current_step.cloud_coverage,
                "precipitation": current_step.precipitation,
                # Upper-air quantities behind the two opt-in sensors; ``None``
                # here means the run's files carried no pressure levels (or,
                # for the freezing level, that the profile could not support
                # one) rather than a sensor fault.
                "freezing_level": current_step.freezing_level,
                "temperature_850hpa": current_step.temperature_850hpa,
            },
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
            "selected_offset": coordinator.radar_frame_offset,
            "size": [radar.image.width, radar.image.height],
            # The map overlay's size and the bytes both pictures cost, so a
            # report about a missing or misplaced overlay says which rendering
            # is in play without needing the images themselves.
            "map_size": [radar.map_image.width, radar.map_image.height],
            "png_bytes": [len(radar.image.png), len(radar.map_image.png)],
            "loop_bytes": [len(radar.loop_png), len(radar.map_loop_png)],
            "max_dbz": radar.image.max_dbz,
            # Coarsened: the crop is centred on the measurement location, which
            # may be the user's home (see ``_coarse``).
            "center": [
                _coarse(radar.image.center_lat),
                _coarse(radar.image.center_lon),
            ],
            "bbox": [
                _coarse(radar.image.south),
                _coarse(radar.image.west),
                _coarse(radar.image.north),
                _coarse(radar.image.east),
            ],
        },
        "warnings": None
        if data.warnings is None
        else {
            "source": data.warnings.source,
            "fetched_at": data.warnings.fetched_at.isoformat(),
            "total_parsed": len(data.warnings.warnings),
            "active_for_location": [
                {
                    "event": w.event,
                    "severity": w.severity,
                    "awareness_level": w.awareness_level,
                    "awareness_type": w.awareness_type,
                    "onset": w.onset.isoformat() if w.onset else None,
                    "expires": w.expires.isoformat() if w.expires else None,
                    "areas": list(w.areas),
                }
                for w in data.active_warnings_for(
                    coordinator.location_latitude, coordinator.location_longitude
                )
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
