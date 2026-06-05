# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.1] - 2026-06-05

### Fixed

- Current weather condition no longer flips to *Unknown* for long stretches. The SHMÚ website's cloud column is populated for only a minority of stations at any moment, and the `stav_poc` code carries no cloud cover, so whenever both were silent the condition fell through to unknown. Conditions are now resolved by a cross-source priority ladder that adds the ALADIN model's current-hour cloud cover as a cloud-aware fallback, so the sky state is filled even when the observations have none. The ladder also fixes a latent case where an observed *cloudy* sky could hide present rain — observed precipitation now outranks an observed cloud reading. The winning source (`website`, `stav_poc`, `aladin`) is shown in the weather entity's `condition_source` attribute and in diagnostics.

## [0.6.0] - 2026-06-03

### Added

- **Measurement location** — the forecast, radar crop and warning relevance can now follow a location separate from the observation station. Choose *Same as the station* (the previous behaviour), *Home Assistant location*, or a *Custom* point on the map, either when adding the integration or later via its **Configure** (options) button. Observations still come from the chosen synoptic station.
- **Name** — the device/entity name is now configurable at setup, defaulting to your Home Assistant location name (e.g. "Home") instead of always being the station name.
- Dataset-freshness diagnostic sensors: *Observation released* / *Observation fetched* and *Forecast model run* / *Forecast fetched*. They surface when the SHMÚ data currently in use was published upstream and when this integration fetched it, so a stale card can be told apart from a stalled poll.

### Fixed

- Hourly forecast no longer lists hours that have already elapsed. An ALADIN run is published from its reference time onward, so until the next run lands the raw step list begins several hours in the past; the hourly forecast is now trimmed to the current hour onward. Daily aggregation is unchanged and still summarises each whole calendar day.
- Diagnostics now coarsen the radar crop's centre/bounding box to ~0.1° so the dump can never pinpoint a private measurement location; the live radar image keeps full precision for map positioning.

## [0.5.2] - 2026-05-20

### Changed

- Entities now ride out a brief upstream blip instead of flipping every value to *Unavailable* the moment a single poll fails. Last good readings, warnings and radar frames are served for up to `OBSERVATION_STALE_AFTER` (30 minutes) after the most recent successful fetch; the diagnostics dump still shows `last_update_success`, `last_update` and `failures_since_success` for visibility, and a multi-cycle outage tips entities to unavailable as before.

## [0.5.1] - 2026-05-19

### Changed

- CI: dropped the obsolete `ignore: brands` from the HACS validation action.
  The HACS action validates the bundled `custom_components/shmu/brand/` assets
  directly, so the check now passes with no exemption — a prerequisite for
  HACS default-store inclusion.

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

[0.6.1]: https://github.com/vaind/ha-shmu/releases/tag/v0.6.1
[0.6.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.6.0
[0.5.2]: https://github.com/vaind/ha-shmu/releases/tag/v0.5.2
[0.5.1]: https://github.com/vaind/ha-shmu/releases/tag/v0.5.1
[0.5.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.5.0
