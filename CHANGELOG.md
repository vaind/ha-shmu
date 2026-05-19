# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-05-19

First public release.

### Added

- **Weather entity** — current conditions for a chosen SHMÚ synoptic station, plus the ALADIN/SHMÚ daily and hourly forecast (`get_forecasts`), decoded from GRIB2 in pure Python with no native dependency.
- **Sensors** — temperature, ground temperature, humidity, pressure, wind speed/gust/bearing, precipitation, snow depth, visibility, global radiation, and a warning-level sensor. The raw WMO present-weather code is available as an opt-in diagnostic sensor.
- **Weather warnings** — a binary sensor that is on while a SHMÚ CAP alert's own polygon covers the station, exposing the full alert details as attributes.
- **Radar** — an image entity rendering the national ODIM_H5 composite (decoded in pure Python), cropped to the station vicinity with a country-border and station-marker overlay, as an animated APNG loop of the recent frames.
- Config-flow setup with the nearest station preselected, English and Slovak translations, and a diagnostics dump with credential/PII redaction.
- Brand icon and logo bundled in `custom_components/shmu/brand/` (served locally via the Home Assistant Brands Proxy API).

### Notes

- Distributed via **HACS** (not Home Assistant core) by design: the current sky condition is read from the SHMÚ website because the open-data files carry no cloud information.
- Home Assistant quality scale: **silver**.

[0.5.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.5.0
