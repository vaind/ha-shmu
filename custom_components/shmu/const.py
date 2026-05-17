"""Constants for the SHMÚ Weather integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "shmu"

CONF_IND_KLI: Final = "ind_kli"

#: SHMÚ publishes a new observation snapshot every 5 minutes, on the UTC
#: 5-minute grid, finalised at the boundary. We poll on that same grid so we
#: pick up each snapshot promptly instead of drifting up to ~5 min behind it.
#: Raise this (e.g. 10) to halve the request rate if SHMÚ ever rate-limits;
#: the grid stays aligned, we just skip alternate snapshots.
POLL_INTERVAL_MINUTES: Final = 5

#: Fire this many seconds *after* each grid boundary. Covers publish latency
#: and tolerates the HA host clock running up to this much fast (well under a
#: minute, as requested, so we still get the freshest snapshot).
POLL_OFFSET_SECONDS: Final = 45

#: SHMÚ data is CC BY 4.0 and must be attributed wherever it is shown.
ATTRIBUTION: Final = "Data © Slovenský hydrometeorologický ústav (SHMÚ), CC BY 4.0"

MANUFACTURER: Final = "Slovenský hydrometeorologický ústav"

#: SHMÚ data is CC BY 4.0 and must be attributed wherever it is shown.
ATTRIBUTION: Final = "Data © Slovenský hydrometeorologický ústav (SHMÚ), CC BY 4.0"

MANUFACTURER: Final = "Slovenský hydrometeorologický ústav"
