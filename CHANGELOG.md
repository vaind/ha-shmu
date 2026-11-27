# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A new calendar, `calendar.<device>_weather_warnings`, shows each weather warning at your location as an event with SHMÚ's full text. Unlike the warning sensor, it also holds the warnings issued for later, so they appear in the *Calendar* panel ahead of time and a calendar trigger can notify you before one comes into force.

## [1.1.0] - 2026-11-26

### Added

- Each warning in the weather warning sensor's `warnings` attribute now carries SHMÚ's full warning text: `description` says what to expect, such as how much snow will fall, and `instruction` says what to do. Until now only the `headline` was published, and it is often generic.

## [1.0.1] - 2026-11-26

### Fixed

- Weather warnings no longer miss alerts that SHMÚ publishes a few minutes into an update. SHMÚ writes one warnings update over up to five minutes, and a refresh in that window used to keep the partial set until the next update, hours later, so a location could show yellow while an orange warning was in force. Every refresh now also reads the alerts added since the previous one, and a new update replaces the previous one only once SHMÚ has finished writing it, 5 to 10 minutes after it is complete.
- Warnings for the Piešťany district no longer show up everywhere in Slovakia. SHMÚ sends them without the district's outline, and the warning sensors treated them as covering the whole country. They now cover only the district, outlined from the map on SHMÚ's warnings page, and the same applies to any other district whose warning arrives without an outline.
- Forecast precipitation is no longer about a tenth of SHMÚ's own forecast. Each ALADIN file holds one hour's precipitation, but the integration read it as a running total and kept only the hourly increase, so steady rain or snow showed as almost dry and its hours as *Cloudy*. The hourly amounts, daily totals and conditions now match SHMÚ's forecast.
- The hourly forecast now has a step for every hour up to the model's horizon. Past 48 hours it used to list only every third hour, which left two hours in three out of the daily precipitation total.

## [1.0.0] - 2026-11-19

The first stable release. From now on, a breaking change to the entities, their states and units, the documented attributes, the configuration options or the map plugin comes only with a new major version. The [Versioning](https://github.com/vaind/ha-shmu#versioning) section of the README lists exactly what is covered.

### Changed

- Entities that had a generic icon now have a fitting one: snow depth, visibility, wind gust, ground temperature, freezing level, weather code, warning level, the radar images and the radar frame selector. An icon you set yourself is kept.

## [0.12.2] - 2026-11-16

### Fixed

- The daily forecast no longer shows rain on a day forecast to stay almost dry. A single damp hour used to put a rain icon on the whole day, even when the day added up to 0.2 mm. A day now shows rain, snow or a thunderstorm only when it adds up to at least 1 mm, and otherwise shows the sky around noon. The day's precipitation amount is unchanged.

## [0.12.1] - 2026-11-05

### Fixed

- The weather entity's `observation_time` attribute is no longer an hour early. SHMÚ switched its observation timestamps from UTC+1 to UTC on 2026-10-25, while its metadata still says UTC+1. The readings themselves were never affected.

## [0.12.0] - 2026-10-15

### Added

- **Every SHMÚ automatic weather station can now be picked, not only the 27 synoptic ones.** That makes 94 to choose from, roughly halving the typical distance to the nearest station. Existing installations are unchanged, and a new one preselects the nearest station of the larger list.
  - Synoptic stations are marked ★ because they report the most. The others all measure temperature, humidity, wind and precipitation, but only some measure pressure, present weather or visibility, and the sensors for what a station does not measure are unavailable.
  - A station that cannot compute its own **Sea-level pressure**, for lack of a barometer or a known elevation, shows the value of the nearest station within 40 km that can. The sensor's `source_name` and `source_distance_km` attributes name that station, and the weather entity's pressure follows the same sensor.
  - At Banská Bystrica, Spišské Vlachy, Žabokreky, Turzovka and Liptovský Mikuláš, the present-weather sensor reports drizzle or rain far more often than the radar and the station's own gauge see it, so their weather condition ignores those reports. The **Weather code** sensor still shows the code SHMÚ publishes.
  - Sliač is no longer offered for new installations, because SHMÚ has not published its observations for over a month. Existing Sliač installations still load, but their station sensors stay unavailable until SHMÚ publishes again.
- **The weather condition now uses the radar.** An echo of 20 dBZ or more within about 1 km of the station means precipitation (rain, sleet or snow by temperature), and no echo there overrules the forecast model when it predicts rain or a thunderstorm. For a station without a present-weather sensor, a *rainy* condition is now right 61 % of the time instead of 35 %. A radar frame older than 20 minutes is ignored. `condition_source` reads `radar` when the radar decides the condition.

### Changed

- **A sensor whose reading is missing is now *unavailable* instead of *unknown*.** This covers station readings, the rain-gauge and sea-level pressure sensors, and the model-based freezing level and 850 hPa temperature. Home Assistant reserves *unknown* for a value that is only temporarily missing, and many stations never measure some quantities. History and statistics treat both states as a gap, but an automation or template that tested these sensors for `unknown` should test for `unavailable` instead.

## [0.11.1] - 2026-10-15

### Fixed

- Fewer `SHMÚ … unavailable, keeping previous: … Server disconnected` warnings and `Error fetching shmu data` errors. SHMÚ's server now and then hangs up on a request without answering, so a source fell back to its previous data, or the whole poll failed, until the next poll. Such a request is now retried up to two more times. Any other failure still falls back at once.

## [0.11.0] - 2026-10-13

### Changed

- **Breaking: the Precipitation and Rain gauge precipitation sensors now report intensity in mm/h instead of an amount in mm.** SHMÚ publishes the rain of a single minute once every five minutes, so the old value undercounted roughly five times when summed. Each sensor now shows the hourly rate that minute implies (the 1-minute sum × 60, so 0.2 mm reads 12 mm/h). Home Assistant raises a *The unit of … has changed* repair: delete the old statistics under *Developer tools → Statistics* rather than keep them under the new unit, where they would read sixty times too low. Multiply any automation threshold on these sensors by 60.
- **Wind bearing is now a wind direction**, so its long-term statistics take the circular mean and a wind swinging between 350° and 10° averages to north rather than to 180°. Home Assistant raises a *The mean type of … has changed* repair until you delete the old statistics under *Developer tools → Statistics*.
- **Snow depth is now a distance**, so you can display it in another unit from the entity settings.
- **Requires Home Assistant 2026.3 or newer** (was 2025.1). Home Assistant 2026.3 is the first release on Python 3.14, which the integration is now developed and tested on. Older Home Assistant versions keep the release they have.
- **Removed three debugging attributes** before 1.0 makes the attributes a commitment: `data_source` and `raw_condition` from the weather entity, and `source` from the `radar` and `radar_map` images. The diagnostics download still has the same information. A template that read `raw_condition` can use the entity's state instead, which differs only in showing *clear-night* rather than *sunny* after sunset.
- The radar scrubber (`number.<device>_radar_frame_selector` and the `radar_frame` and `radar_map_frame` images) is now documented as provisional, because frame-by-frame playback in the map plugin is likely to replace it ([#52](https://github.com/vaind/ha-shmu/issues/52)). Its behaviour is unchanged.

### Fixed

- Home Assistant no longer freezes for several seconds whenever a new ALADIN forecast run arrives, at every startup and up to four times a day. The integration unpacked every forecast map on Home Assistant's event loop to read one grid point. It now unpacks only that point, which takes milliseconds, and does it in a worker thread.
- No more `SHMÚ warnings unavailable, keeping previous: No entries matching '^\\d{8}/$' …` warning every five minutes in calm weather. SHMÚ empties its warnings folder when nothing is in force, and the integration now reads that as "no warnings" instead of a failed fetch.
- Malformed data from SHMÚ now shows up as an ordinary failed update instead of an "unexpected error" traceback, and a change to the SHMÚ website's layout is treated like a website outage instead of logging a warning every five minutes.
- The station's sensors now go unavailable when SHMÚ stops publishing new observation files, instead of showing the last reading as current for as long as the stall lasts.
- Removing the integration, or changing its options, during a poll no longer leaves the old instance polling in the background until Home Assistant restarts.
- The weather condition no longer stays stuck on an old reading while the SHMÚ website is unreachable. The website publishes one report per hour, so a scrape is now set aside once it is an hour old, and the condition falls back to the station's present-weather code and the ALADIN model.
- An outage of a supplementary SHMÚ source (warnings, forecast, radar, website conditions or rain gauges) no longer writes the same warning every five minutes. The integration now logs a warning once when the source goes down and an info line when it comes back.

## [0.10.0] - 2026-09-02

### Added

- **The radar can now be panned and zoomed on a map.** Three new image entities, `radar_map`, `radar_map_loop` and `radar_map_frame`, carry the same frames as the radar pictures, but as the whole national composite at the radar's native ~0.3 km resolution, undecorated and transparent where there is no echo. They publish the box they cover, so a map card can drape them over its own map, and the same scrubber slider drives both kinds.
- The plugin that puts them on a map **ships with the integration** at `/shmu_static/radar-map-overlay.js`. You install only the [ha-map-card](https://github.com/nathan-gs/ha-map-card) card itself, and the README has a ready-made card under [Zoomable radar on a map](https://github.com/vaind/ha-shmu#zoomable-radar-on-a-map). The overlay lines up exactly, because the radar grid and web maps both use spherical Mercator.

### Fixed

- The `bbox_*` attributes now describe the area a radar picture actually covers. For the downsampled station crop, the box fell short by up to one sampled cell, under a kilometre.

### Changed

- Radar frames are now decoded once and rendered twice, in a worker thread, so the first poll after a restart no longer blocks Home Assistant's event loop. The extra rendering costs about 1.2 MB of memory.

## [0.9.0] - 2026-08-26

### Added

- New **Rain gauge precipitation** sensor from SHMÚ's network of ~190 automatic rain gauges, about three times denser than the 27 synoptic stations. Across the country, the nearest gauge is a median 10 km away against 28 km for the nearest synoptic station. The sensor reads the gauge nearest your measurement location and names it, with its distance, in its attributes. The station's own **Precipitation** sensor is unchanged, because the two measure different places.
- Two new **opt-in** sensors from the ALADIN model: **Freezing level**, the height of the 0 °C isotherm above sea level, and **Temperature at 850 hPa**, the standard air-mass indicator at roughly 1450 m. The freezing level is not the snow line, which usually sits a few hundred metres lower. Enable them from the device page.

### Fixed

- The weather entity's `observation_time` attribute is no longer an hour in the future. SHMÚ stamps observations in UTC+1, as its metadata says, but the integration read them as UTC. The readings themselves were never affected.
- The forecast now refreshes with every ALADIN run (four a day) instead of once a day. Only the 00 UTC run reaches +102 h, and the integration discarded the other three runs, which stop at +72 h, so the forecast could be up to 24 hours old.
- Today's daily forecast no longer shows *yesterday* as its first entry in the hours after midnight.

### Changed

- Forecast steps from successive model runs are now combined into one series, newest run winning per hour. A +72 h run alone would cut a day off the daily forecast, so merging keeps the full length while still refreshing four times a day. Diagnostics show the runs in use under `contributing_runs`.

## [0.8.0] - 2026-07-23

### Added

- New **Sea-level pressure** sensor. SHMÚ's pressure is the raw barometer reading at the station, which at altitude sits well below the ~1013 hPa people expect (Lomnický Štít at 2635 m reads ≈793 hPa). The new sensor reduces it to sea level using the station's elevation and temperature, so it is comparable with weather charts and other stations. The **Pressure** sensor still reports the raw reading.

### Changed

- The weather entity's pressure is now sea-level pressure, on the same basis as the forecast's, so the two no longer differ by the station's elevation offset.

## [0.7.1] - 2026-07-21

### Fixed

- The daily forecast no longer shows a truncated final day as a whole day. The model's last day usually ends in the morning, so its "high" was the pre-dawn temperature. A day is now shown only when the forecast covers it to its end.
- Forecast conditions past +48 h no longer overstate rain. Those steps cover three hours each, but their precipitation was classified as if it fell in one, so light drizzle read as *Pouring*. Precipitation is now classified by its hourly rate.
- Today's daily high and low no longer miss the early morning when a model run starts later in the day. The previous run's earlier hours for today are now carried forward.

## [0.7.0] - 2026-06-12

### Added

- Diagnostics now explain how the current condition was decided: the `derived_condition` block lists every source's candidate and which one won, a `veto` block shows when a station's observation overrode a model storm, and the `forecast` block reports the `current_step` used.

### Fixed

- The weather condition no longer shows a model-forecast *Lightning, rainy* (or rain) while the station reports calm, dry weather. When a station observes no significant weather and no precipitation, the condition now falls back to the model's sky state (e.g. *Cloudy*). Observed weather is never overruled, and stations without a present-weather sensor are unaffected.

## [0.6.1] - 2026-06-05

### Fixed

- The weather condition no longer flips to *Unknown* for long stretches. The SHMÚ website's cloud column is empty for most stations, and the station's present-weather code carries no cloud cover, so the condition often had no source. The ALADIN model's current cloud cover now fills that gap. Observed precipitation also now outranks an observed cloudy sky. The weather entity's `condition_source` attribute shows the winning source (`website`, `stav_poc` or `aladin`).

## [0.6.0] - 2026-06-03

### Added

- **Measurement location**: the forecast, the radar crop and warning relevance can follow a location other than the station: *Same as the station* (the previous behaviour), *Home Assistant location*, or a *Custom* point on the map. Set it when adding the integration or later under **Configure**.
- **Name**: the device and entity name is now configurable at setup and defaults to your Home Assistant location name (e.g. "Home") instead of the station name.
- Diagnostic sensors for data freshness: *Observation released*, *Observation fetched*, *Forecast model run* and *Forecast fetched*, so a stale card can be told apart from a stalled poll.

### Fixed

- The hourly forecast no longer lists hours that have already passed.
- Diagnostics now round the radar crop's centre and bounding box to ~0.1°, so a download can never pinpoint a private measurement location.

## [0.5.2] - 2026-05-20

### Changed

- Entities now ride out a brief upstream outage instead of turning *Unavailable* the moment one poll fails. The last good readings, warnings and radar frames are served for up to 30 minutes after the last successful fetch.

## [0.5.1] - 2026-05-19

### Changed

- CI: dropped the obsolete `ignore: brands` from the HACS validation, which now validates the bundled `custom_components/shmu/brand/` icons directly.

## [0.5.0] - 2026-05-19

First public release.

### Added

- **Weather entity**: current conditions for a chosen SHMÚ synoptic station, and the ALADIN daily and hourly forecast (`get_forecasts`), decoded from GRIB2 in pure Python.
- **Sensors**: temperature, ground temperature, humidity, pressure, wind speed, gust and bearing, precipitation, snow depth, visibility, global radiation and warning level. The raw WMO present-weather code is an opt-in diagnostic sensor.
- **Weather warnings**: a binary sensor that is on while a SHMÚ warning covers the station, with the alert details as attributes.
- **Radar**: an animated loop of the national radar composite, decoded in pure Python and cropped to the station with country borders and a station marker.
- Setup with the nearest station preselected, English and Slovak translations, and a diagnostics download with personal data redacted.
- Brand icon and logo bundled in `custom_components/shmu/brand/`.

### Notes

- Distributed through **HACS** rather than Home Assistant core by design, because the current sky condition is read from the SHMÚ website.
- Home Assistant quality scale: **silver**.

[1.1.0]: https://github.com/vaind/ha-shmu/releases/tag/v1.1.0
[1.0.1]: https://github.com/vaind/ha-shmu/releases/tag/v1.0.1
[1.0.0]: https://github.com/vaind/ha-shmu/releases/tag/v1.0.0
[0.12.2]: https://github.com/vaind/ha-shmu/releases/tag/v0.12.2
[0.12.1]: https://github.com/vaind/ha-shmu/releases/tag/v0.12.1
[0.12.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.12.0
[0.11.1]: https://github.com/vaind/ha-shmu/releases/tag/v0.11.1
[0.11.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.11.0
[0.10.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.10.0
[0.9.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.9.0
[0.8.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.8.0
[0.7.1]: https://github.com/vaind/ha-shmu/releases/tag/v0.7.1
[0.7.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.7.0
[0.6.1]: https://github.com/vaind/ha-shmu/releases/tag/v0.6.1
[0.6.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.6.0
[0.5.2]: https://github.com/vaind/ha-shmu/releases/tag/v0.5.2
[0.5.1]: https://github.com/vaind/ha-shmu/releases/tag/v0.5.1
[0.5.0]: https://github.com/vaind/ha-shmu/releases/tag/v0.5.0
