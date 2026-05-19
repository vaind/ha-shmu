# SHMÚ Weather for Home Assistant

A Home Assistant integration for Slovak weather data published by the
**Slovak Hydrometeorological Institute (SHMÚ)**.

[![CI](https://github.com/vaind/ha-shmu/actions/workflows/ci.yml/badge.svg)](https://github.com/vaind/ha-shmu/actions/workflows/ci.yml)
[![HACS: Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

> Current conditions, weather warnings, and the ALADIN/SHMÚ daily & hourly
> forecast — decoded from GRIB2 in pure Python, with no native dependency.

## ⚠️ Disclaimer

- This is an **unofficial, community project**. It is **not affiliated with,
  developed by, endorsed by, or supported by the Slovak Hydrometeorological
  Institute (SHMÚ)** in any way. "SHMÚ" is used only to identify the data
  source.
- The integration reads data from public SHMÚ endpoints that have no stable
  API contract; it can break if SHMÚ changes them.
- Provided **"as is", without warranty of any kind. Use at your own risk.**
  Do not rely on it for safety-critical decisions; always consult official
  SHMÚ channels for authoritative weather warnings.

## Features

- **Weather entity** — current conditions for a chosen SHMÚ synoptic station.
- **Sensors** — temperature, ground temperature, humidity, pressure, wind
  speed/gust/bearing, precipitation, snow depth, visibility, global radiation,
  and a warning-level sensor (the raw WMO weather code is an opt-in
  diagnostic).
- **Weather warnings** — a binary sensor (with full alert details as
  attributes) that is on while a SHMÚ CAP alert covers your station, decided
  by the alert's own polygon.
- One shared, change-detecting fetch per cycle, aligned to SHMÚ's upstream
  UTC 5-minute publish grid with an offset that auto-tunes to the observed
  publish lag, so data is fresh rather than up to a poll-interval behind.
  A station that drops out of one snapshot keeps its last reading (no
  flicker) until it is genuinely stale.

## Installation (HACS)

This integration relies on the SHMÚ website for the current sky condition (the
open-data files contain no cloud information — see
[Why HACS](CONTRIBUTING.md#why-hacs-and-not-home-assistant-core)), so it is
distributed via HACS rather than Home Assistant core.

1. HACS → Integrations → ⋮ → *Custom repositories* → add this repository as an
   *Integration*.
2. Install **SHMÚ Weather**, then restart Home Assistant.
3. *Settings → Devices & Services → Add Integration → SHMÚ Weather*. The
   station nearest your Home Assistant location is preselected; pick any of
   the 27 synoptic stations. Add the integration again for more stations.

## Removing the integration

1. *Settings → Devices & Services → SHMÚ Weather → ⋮ → Delete* for each
   configured station. This removes its device, entities and history.
2. Optionally, in HACS → *SHMÚ Weather* → ⋮ → *Remove*, then restart Home
   Assistant to delete the integration files.

No external account or credential exists, so nothing else needs cleaning up.

## Data source & attribution

Weather and climate data © **Slovenský hydrometeorologický ústav (SHMÚ)**,
provided via <https://opendata.shmu.sk/> under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This project is not
affiliated with or endorsed by SHMÚ.

## License

Code is MIT licensed (see [LICENSE](LICENSE)). SHMÚ data retains its CC BY 4.0
license and must be attributed accordingly.
