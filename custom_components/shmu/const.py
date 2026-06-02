"""Constants for the SHMÚ Weather integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "shmu"

CONF_IND_KLI: Final = "ind_kli"

#: Measurement-location config (the point used for the forecast, radar crop and
#: warning relevance — *separate* from the observation station, which is always
#: keyed by ``ind_kli``). Stored in ``entry.options`` so the options flow can
#: edit it without re-adding the integration.
CONF_LOCATION_MODE: Final = "location_mode"
#: The :class:`LocationSelector` field; present only when the mode is custom.
CONF_LOCATION: Final = "location"

#: Track the observation station's own coordinates (the historical behaviour).
LOCATION_MODE_STATION: Final = "station"
#: Track Home Assistant's configured home coordinates. The value must **not**
#: contain the substring ``"home"``: the mode is surfaced in diagnostics, which
#: deliberately never leak the user's home location.
LOCATION_MODE_HASS: Final = "hass"
#: Track an explicit point the user picks on the map.
LOCATION_MODE_CUSTOM: Final = "custom"

#: All modes, in the order shown in the selector.
LOCATION_MODES: Final = (
    LOCATION_MODE_STATION,
    LOCATION_MODE_HASS,
    LOCATION_MODE_CUSTOM,
)
#: Absence of options (existing entries) resolves here, preserving behaviour.
DEFAULT_LOCATION_MODE: Final = LOCATION_MODE_STATION

#: SHMÚ publishes a new observation snapshot every 5 minutes, on the UTC
#: 5-minute grid, finalised at the boundary. We poll on that same grid so we
#: pick up each snapshot promptly instead of drifting up to ~5 min behind it.
#: Raise this (e.g. 10) to halve the request rate if SHMÚ ever rate-limits;
#: the grid stays aligned, we just skip alternate snapshots.
POLL_INTERVAL_MINUTES: Final = 5

#: The poll fires at ``boundary + offset``. The offset auto-tunes to the
#: real-world publish lag observed from each file's ``Last-Modified`` (so we
#: track SHMÚ if it speeds up/slows down) plus a fixed safety pad, clamped to
#: a sane range. Pad covers HA-host clock skew; the floor keeps us from ever
#: firing exactly at the boundary; the ceiling bounds a pathological sample.
POLL_OFFSET_PAD_SECONDS: Final = 30
POLL_OFFSET_MIN_SECONDS: Final = 30
POLL_OFFSET_MAX_SECONDS: Final = 120

#: A station can drop out of one 5-minute snapshot. Keep serving its last
#: reading across such gaps (no UI flicker) but treat it as genuinely
#: unavailable once we have not obtained a fresh reading for this long.
OBSERVATION_STALE_AFTER: Final = timedelta(minutes=30)

#: SHMÚ data is CC BY 4.0 and must be attributed wherever it is shown.
ATTRIBUTION: Final = "Data © Slovenský hydrometeorologický ústav (SHMÚ), CC BY 4.0"

MANUFACTURER: Final = "Slovenský hydrometeorologický ústav"
