# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- New **Rain gauge precipitation** sensor, reading SHMÚ's automatic rain-gauge network — a second network of ~190 gauges, disjoint from and roughly three times denser than the 27 synoptic stations (~16 km spacing against ~40 km).
Precipitation is the measurement that varies most sharply over short distances, so this matters: sampled over a grid of points across the country, the nearest rain gauge is a median **10 km** away against **28 km** for the nearest synoptic station, and is the closer of the two at 92% of points.
The gauge is chosen from your measurement location (as the forecast and radar already are) and named in the sensor's attributes, along with its distance.
Your station's existing **Precipitation** sensor is unchanged and still reads the station — the two are different networks measuring different places, so neither silently stands in for the other.
- SHMÚ publishes no coordinates for these gauges, which is why the network went unused until now; they were recovered from the SHMÚ page that plots the gauges on a map and cross-checked against the existing station catalogue, which the same page also carries (the two independent sources agree to a median of 272 m).

### Fixed

- The forecast now refreshes with every ALADIN run (4×/day) instead of once a day. SHMÚ publishes four runs daily, but only the 00 UTC one reaches +102 h — the 06/12/18 UTC runs stop at +72 h. The integration required every hour through +102, so it silently discarded three runs in four and served a forecast up to 24 hours old. Today's forecast is noticeably closer to reality as a result: on a live comparison the discarded 06 UTC run corrected the current afternoon by 1.5–2.4 °C and raised the next day's high by 0.7 °C.
- Today's daily forecast no longer shows *yesterday* as its first entry in the hours after midnight. The series is now re-bounded to the current local day on every update, rather than only when a new model run appears — between local midnight and the next run being published (several hours), the leading day was the one that had just ended.

### Changed

- Forecast steps from successive model runs are now combined into one series, newest run winning per hour, instead of the newest run replacing the previous one. This keeps the full forecast length while still refreshing 4×/day: on its own a +72 h run stops short of its last local day, so that day would be dropped and the daily forecast would lose a day (in exchange for the freshness). Merging keeps both — today covered from midnight, the last day intact, and the near term from the newest run. Diagnostics gained a `contributing_runs` field showing which runs the series is built from.

## [0.8.0] - 2026-07-23

### Added

- New **Sea-level pressure** sensor. SHMÚ reports `tlak` as the raw barometer reading *at the station* (QFE), which on an elevated station sits well below the ~1013 hPa people expect and is not comparable between stations (e.g. Lomnický Štít at 2635 m reads ≈793 hPa). The new sensor reduces that reading to mean sea level (QFF) using the station's elevation and current temperature, so it lines up with synoptic charts and other weather sources. The existing **Pressure** sensor is unchanged and still reports the raw station value.

### Changed

- The weather entity's pressure attribute now reports sea-level (QFF) pressure instead of the raw station reading. This puts "now" on the same datum as the forecast (whose pressure is already reduced to sea level), so the two no longer jump by the station's elevation offset.

## [0.7.1] - 2026-07-21

### Fixed

- Daily forecast no longer shows a truncated final day as if it were a whole day. The ALADIN model horizon is +102 h, so the last local calendar day is usually covered only into the morning (for a 00 UTC run it stops around 08:00 local); its "high" was therefore the pre-dawn temperature rather than the real afternoon peak (e.g. a summer Saturday reading 16.8 °C instead of ~26 °C). A day is now summarised only when the forecast horizon reaches its end, so the last, partly-covered day is dropped instead of being shown with a misleading high/low and total.
- Daily and hourly forecast conditions past +48 h no longer overstate rain. Beyond +48 h ALADIN steps are 3-hourly, but each step's precipitation was classified as if it fell in a single hour, so a light drizzle spread over three hours read as *Pouring* and a trace could surface a phantom *Lightning, rainy*. Precipitation is now classified by its per-hour intensity, so the later forecast days reflect the actual rain rate.
- Today's daily high/low no longer omits the early morning when a fresh model run starts later in the day. A run begins at its reference hour (00/06/12/18 UTC), so the newest one can start partway through the current day; its earlier hours were simply absent, so today's low could be taken from mid-morning rather than the dawn minimum. The previous run's earlier steps for today are now carried forward, so today is summarised from model data spanning the whole local day (the forecast stays entirely model-sourced — no observation is blended in).

## [0.7.0] - 2026-06-12

### Added

- Diagnostics now explain *how* the current condition was decided: the `derived_condition` block lists every source that produced a candidate (with its tier, priority, proposed condition, and which one won) and a `veto` block showing when a station's "no significant weather" observation overrode a model storm. The `forecast` block also reports the `current_step` the resolver used. This makes "why is it showing X" answerable straight from a downloaded dump.

### Fixed

- Weather condition no longer shows a model-forecast *Lightning, rainy* (or rain) while the station itself reports calm, dry weather. The ALADIN model fills the condition when the observations have no sky reading, but on a convective summer afternoon its current-hour cell could predict a thunderstorm over a station that was actually dry. Now, when a station observes no significant present weather (`stav_poc` 0 and no precipitation), that observation vetoes the model's precipitation/storm claim and the condition falls back to the model's cloud-only sky state (e.g. *Cloudy*) instead. Observed present weather is never vetoed, and stations that do not report `stav_poc` are unaffected.

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

[0.8.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.8.0
[0.7.1]: https://github.com/vaind/ha-shmu/releases/tag/v0.7.1
[0.7.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.7.0
[0.6.1]: https://github.com/vaind/ha-shmu/releases/tag/v0.6.1
[0.6.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.6.0
[0.5.2]: https://github.com/vaind/ha-shmu/releases/tag/v0.5.2
[0.5.1]: https://github.com/vaind/ha-shmu/releases/tag/v0.5.1
[0.5.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.5.0
