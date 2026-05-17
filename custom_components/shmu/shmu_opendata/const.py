"""Constants for the SHMÚ open-data client."""

from __future__ import annotations

from typing import Final

BASE_URL: Final = "https://opendata.shmu.sk"

#: Directory holding per-day folders of 5-minute automatic-station snapshots.
OBSERVATIONS_PATH: Final = "/meteorology/climate/now/data"

#: Directory holding per-day / per-issuance folders of CAP 1.2 alert XML.
WARNINGS_PATH: Final = "/meteorology/weather/alerts/cap"

DEFAULT_TIMEOUT: Final = 30.0

#: Identifies this client to SHMÚ (they log client IPs for abuse protection;
#: a clear UA is courteous and aids their operations).
USER_AGENT: Final = "shmu-opendata (+https://github.com/vaind/ha-shmu)"
