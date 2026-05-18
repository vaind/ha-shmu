"""Constants for the SHMÚ open-data client."""

from __future__ import annotations

from typing import Final

BASE_URL: Final = "https://opendata.shmu.sk"

#: Directory holding per-day folders of 5-minute automatic-station snapshots.
OBSERVATIONS_PATH: Final = "/meteorology/climate/now/data"

#: Directory holding per-day / per-issuance folders of CAP 1.2 alert XML.
WARNINGS_PATH: Final = "/meteorology/weather/alerts/cap"

#: ALADIN 4.5 km NWP tree: ``<this>/YYYYMMDD/HHHH/al-grib_sk_NNN-…-nwp-.grb``.
#: Runs at 00/06/12/18 UTC; forecast hours 000-102 (one GRIB2 file each).
FORECAST_PATH: Final = "/meteorology/weather/nwp/aladin/sk/4.5km"

#: Radar composite tree: ``<this>/<product>/YYYYMMDD/T_PA?V22_C_LZIB_<ts>.hdf``
#: (ODIM_H5). A new national composite every 5 minutes; ~32 days retained.
RADAR_PATH: Final = "/meteorology/weather/radar/composite/skcomp"

#: Default composite: column-maximum reflectivity — the standard "is it
#: raining / where are the storms" radar picture. ``cappi2km`` is the other
#: reflectivity product; both decode identically (ODIM quantity ``DBZH``).
DEFAULT_RADAR_PRODUCT: Final = "zmax"

#: Forecast hours to fetch per run: hourly to +48 h, then 3-hourly to +102 h
#: (the model's horizon). ≈67 files (~11 MB) once per run — *not* per
#: observation poll. Trimmed if a run does not publish the full set.
FORECAST_HOURS: Final = (*range(0, 49), *range(51, 103, 3))

DEFAULT_TIMEOUT: Final = 30.0

#: Identifies this client to SHMÚ (they log client IPs for abuse protection;
#: a clear UA is courteous and aids their operations).
USER_AGENT: Final = "shmu-opendata (+https://github.com/vaind/ha-shmu)"
