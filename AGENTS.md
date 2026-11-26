# AGENTS.md

Guidance for AI coding agents working in this repo.
Read it before changing data-fetching or condition logic: it records the non-obvious constraints learned by reverse-engineering the SHMÚ source.

Setup, the pre-push quality gate and the general ground rules (the vendored-library boundary, offline tests, TLS handling, scraper isolation) are in [CONTRIBUTING.md](CONTRIBUTING.md) and are not repeated here.
Read it before your first change.
The rule agents break most often: **don't hard-wrap Markdown prose**, write one sentence per line.

## The rule specific to this data source

**Verify upstream assumptions against the live server** before encoding them, and record what you verified, with the date, under *Non-obvious data-source facts*.
Don't add workarounds for failure modes that don't occur.
Where a verified fact is cheap to assert, pin it in `tests_e2e/` too, so the daily live run notices when SHMÚ stops honouring it.
A `#N` after a fact is the PR or issue that holds the full measurement.

## Keeping the docs short

AGENTS.md, README.md and CHANGELOG.md each have one reader, and anything that reader can do without belongs somewhere else.
Get shorter by saying fewer things, never by dropping the words a sentence needs.
Before you add to one of them, look for the fact already stated there or in another file, and change that instead of adding a second version.

- **AGENTS.md is for agents changing the code.** A fact keeps four things: the fact, the date it was verified, the rule it implies for the code, and when to re-check it.
  - The evidence behind it (sample sizes, tables, timelines, the method) goes in the PR description, and the fact ends with that PR's `#N`.
  - History ("we used to…") gets one clause, and only where it explains a guard that would otherwise look removable.
  - When a fact changes, rewrite it in place rather than appending a dated update below it, since git keeps the old version.
  - Recipes and per-module detail live in the module's docstring, so point there instead of copying them.
  - A new fact rarely needs more than five sentences. More usually means evidence that belongs in the PR.
  - Delete a fact once the code or the upstream behaviour it describes is gone.
- **README.md is for users.** It says what the integration does, how to set it up, what each entity and attribute means, and what to do when something looks wrong.
  - Explain a design choice in one sentence of user terms, and leave the mechanism to AGENTS.md.
  - Keep the numbers a user acts on (how long a reading is kept, bandwidth, the forecast horizon) and drop the ones that only justify a threshold.
  - Say a thing once, in the section a user would look in, and link to it from the others.
- **CHANGELOG.md is for users upgrading.** An entry says what they will see change and what they must do, in one to three sentences, rarely more than about 100 words.
  - Name the symptom a user would recognise and give the cause in at most one clause. Leave out function names, timings and how the bug was found.
  - A breaking change may run longer, but only for the steps to migrate.
  - The release workflow publishes a section verbatim as the GitHub Release (see [Releasing](CONTRIBUTING.md#releasing)), so get each entry short in the PR that adds it.
- **All three** follow the same style: one sentence per line, no em-dashes (use " - " or split the sentence), and no semicolons between clauses (write two sentences instead).

## Layout

| Path | What |
|---|---|
| `custom_components/shmu/shmu_opendata/` | Vendored client library (no HA deps) |
| `custom_components/shmu/` | Home Assistant integration (the glue) |
| `custom_components/shmu/frontend/` | The map-card radar plugin, served from `/shmu_static/` |
| `custom_components/shmu/brand/` | Bundled integration icons (`brand_src/` holds the SVG sources) |
| `tests/` | Fast offline library tests |
| `tests/components/` | HA integration tests (`pytest-homeassistant-custom-component`) |
| `tests_e2e/` | Live tests against SHMÚ, run daily by `e2e.yml`, the only tests allowed on the network |

- `manifest.json` `requirements` is **empty**: the vendored library is bundled and `aiohttp` ships with HA. The library is HACS-only by design, not on PyPI (see [Why HACS](CONTRIBUTING.md#why-hacs-and-not-home-assistant-core)).
- ty type-checks only the vendored library (`[tool.ty]` in `pyproject.toml`), with its off-by-default `unsound-*` and `missing-type-argument` rules on. Ruff's `ANN` rules require annotations there, which ty does not check.

## Non-obvious data-source facts

### The server

- **opendata.shmu.sk serves a broken TLS chain**: it sends only the leaf cert and omits the Sectigo intermediate ("Sectigo Public Server Authentication CA DV R36").
  We bundle that intermediate in `custom_components/shmu/shmu_opendata/certs/` (fetched from the cert's AIA) and add it to a normal trust store.
  **Never** disable verification to fix a TLS error here. Refresh the bundled intermediate instead.
- **It sometimes hangs up without answering, and we retry only that failure** (#69).
  Production logged `Failed to fetch …: Server disconnected` every 30–60 minutes on 2026-10-14/15 (aiohttp 3.14.4), on every feed, each cleared by the next poll.
  That message is aiohttp's `ServerDisconnectedError`: the server closed the connection before a complete response arrived. A close mid-body reads `Response payload is not completed` (`ClientPayloadError`) instead.
  aiohttp already resends an idempotent request once by itself, so every logged failure hung up twice. `test_recovers_from_a_real_close_without_answer` reproduces that message on loopback.
  `ShmuClient._request` retries `ServerDisconnectedError`, and only it, up to `DISCONNECT_RETRIES` more times, which is safe because a GET is idempotent (RFC 9112 §9.3.1). The website scrape on `www.shmu.sk` goes through `_request` too.
  Every other failure goes straight to the coordinator's keep-previous fallback: timeouts, refused connections, error statuses, truncated bodies and connection resets.
  A reset while connecting (`ClientConnectorError`, `Connection reset by peer`) was seen in production on 2026-11-19 and cleared on a later poll, so we don't retry it (#91).
  It is not the keep-alive race below, which needs a pooled connection. A reset on an established connection (a bare `ClientOSError`), which the race could produce, has not been seen yet, and would be the case for widening the retry.
  **Why it hangs up twice is not established.** Apache closes an idle keep-alive connection after ~5 s while aiohttp pools it for 15 s (verified live 2026-10-15), so the two can race. But a replay of one poll never reused a connection idle for more than ~2 s, so something on the server side, or a busy HA event loop, is more likely.
  If the retry stops being enough, instrument the session with an aiohttp `TraceConfig` (new vs reused connection, idle time per attempt) before changing the bound.
  The server speaks HTTP/1.1 only (no `h2` in ALPN, no `Alt-Svc`), so HTTP/2 and QUIC, which would avoid that race, are not available.
- **It is a plain Apache file index** with no API. Finding the newest file means parsing an HTML directory listing, and hrefs are percent-encoded.
- **It throttles a fast client with `403 Forbidden` on every path** (seen 2026-11-26, #PR).
  An archive scan got the block after about 600 requests in three minutes, six at a time, and the block lifted within a few minutes. About 700 requests one at a time, 1.5 s apart, went through.
  The integration's poll is far below that rate. Scan the archive one request at a time, because the block also stops any Home Assistant on the same network.

### Observations and rain gauges

- **Observations** (`climate/now/data/.../aws1min - ....json`): a new file every 5 min, ~95 stations, several 1-minute records each, keyed by `ind_kli`.
- **`zra_uhrn` is a 1-minute sum, so the precipitation sensors report an intensity, not an amount.**
  Both feeds' metadata say "minute sum" (re-checked live 2026-10-13), at 0.01 mm resolution, and we keep only the newest minute of each 5-minute file.
  The library keeps the raw minute sum (`Observation.precipitation`, `GaugeObservation.precipitation`), which the condition ladder's dry-veto reads. The `precipitation` and `rain_gauge_precipitation` sensors show it ×60 as mm/h (`sensor.precipitation_rate`).
  Don't turn either back into a `PRECIPITATION`/`TOTAL` amount: summing one sampled minute in five undercounts roughly five times.
- **The rain gauges are a second station network, disjoint from the observation stations** (`precipitation/now/data/.../aps1min - ....json`, verified live 2026-08-26, #47).
  The feed has the same envelope and 5-minute cadence as `aws1min` and keeps ~32 days, but it is keyed by `ind_zra` and carries only `zra_uhrn` (mm, 1-minute sum) and `t` (°C at 2 m).
  Its ~190 gauges share no id with the `ind_kli` stations and sit about three times denser (~16 km spacing against ~40 km), so the nearest gauge is usually much closer than the nearest station.
  The `rain_gauge_precipitation` sensor (`gauges.py`) reads it. The station's own `precipitation` sensor still reads `aws1min`, and we keep the two as separate entities on purpose.
  **The gauge coordinates come from the website**, because the open-data server publishes none. The `shmu.sk/sk/?page=838&uhrny=24` map page carries them in an inline JS array of `nazov`/`lat`/`lon`/`uid`, where `uid` is `APS2<ind_zra>` (or `AWS2<ind_kli>` and `AHS<hydro id>` for the other two networks on that map).
  Regenerating `gauges.py` from that page is an offline step, with the recipe in its docstring, so `website.py` stays the only runtime HTML scraper.
  The page's `AWS2` positions agree with the 24 synoptic stations that `stations.py` took from a different page (`?page=318`) to a median 272 m (max 1.2 km), so they are genuine station positions.
  Two leads are dead ends (re-verified 2026-08-26): the INSPIRE record linked from `precipitation/` is not indexed in the RPI CSW, and the national catalogue entry named in `aps1min_metadata.json` holds only the JSON feed itself.
  The map is near-complete, not total (197 ids seen across the archive against 190 on the map), so parsers must tolerate an id that `gauges.py` lacks.
  **A snapshot mixes hours-old backfill in with the current minutes**, so only each gauge's newest record counts, the same rule `parse_observations` applies to `aws1min`.
  **A gauge's presence in a snapshot does not mean it is still reporting**: one gauge, silent for a day, published 73 rows at once whose newest was 29 hours old.
  Those rows step forward minute by minute, so "did `measured_at` advance since the last poll?" would accept them.
  The coordinator instead treats a gauge's newest record as current only within `OBSERVATION_STALE_AFTER` of the newest record anywhere in the same snapshot. Across the archive, 99.8 % of readings sit within 10 minutes of that newest record, and the stragglers are hours behind.
  Comparing against the snapshot rather than the wall clock keeps the test independent of the HA host's clock and of `minuta`'s zone, which changed on 2026-10-25 (next bullet).
  It does not catch the whole feed freezing, which we catch separately by counting only a snapshot whose source path changed.
  A snapshot can be empty (`data: []`), so anything reducing over one must tolerate that.
- **`minuta` reads UTC, and the file names are local time** (#82).
  `_parse_minuta` (`parsers.py`) attaches UTC.
  Measured live 2026-11-05 in both feeds, a file's `Last-Modified` sits a constant ~2 min after its newest `minuta` read as UTC, and the time the stations first see daylight agrees.
  Both feeds' metadata still call the field "termín merania v case SEC" (UTC+1), so **don't trust that label**.
  Through summer 2026 `minuta` read UTC+1 (#46). It switched to UTC on 2026-10-25, two hours after the clock change, together with a one-hour export lag that SHMÚ fixed on 2026-10-27 by rewriting the affected files (#80). The archive therefore no longer shows the lag or that night's first pass.
  **Re-check at the next spring change (2027-03-28).** "`minuta` is UTC" and "`minuta` is local wall time minus one hour" both fit everything measured so far and differ only in summer time. We read UTC because it is the simpler rule.
  If the other rule holds, readings will parse an hour in the future, `tests_e2e` will fail on `FUTURE_SLACK`, and the entity's `observation_time` will be an hour off.
  Nothing else depends on the zone: all records in a file share it, and the freshness rules compare a record against its own snapshot.
- **The `YYYYMMDD/` day folders and the file names are Slovak wall time (CET/CEST), not UTC** (verified live 2026-10-13).
  A file's `Last-Modified` sits within seconds of its name read as Europe/Bratislava time, on either side of it (-8 s to +10 s, which looks like the writer's clock drifting). `test_observation_file_names_are_local_time` pins this.
  **On the autumn clock change (2026-10-25), SHMÚ overwrote the first pass's `02-xx` files in place** (#80). Each day listing keeps its 288 uniquely named files, and the repeated hour's names hold the second pass.
  `_latest_dated_file` picks the newest name (`max(files)`), which stayed the first pass's `02-55-00` until `03-00-00` appeared, so the station sensors were unavailable for half an hour.
  That gap was the feed's: because of the export lag (previous bullet), the second pass carried no newer data.
  Choosing the newest file by `Last-Modified`, or keying the cache on content, would have replaced the readings with older ones and then replayed that hour as current, so `max(files)` stays.
  **Look at both listings again after the next autumn change (2027-10-31)**, since this night's behaviour followed from a lag that may not recur.
- **`tlak` is station-level pressure (QFE), not reduced to sea level** (verified 2026-07-21: Lomnický Štít at 2635 m reads ≈793 hPa).
  The forecast's `PRMSL` is already reduced to sea level, so the two are on different datums.
  The `pressure` sensor shows `tlak` as is. `pressure.py` (`sea_level_pressure`) reduces it to QFF for the `sea_level_pressure` sensor and the weather entity's `native_pressure`, from the station's `elevation` and current temperature (the barometric formula with the ICAO lapse rate).
  It returns `None` when pressure or temperature is missing rather than guess.
- **`stav_poc` (present-weather code) is per-station, not time-sparse**: only ~35 of 95 stations report it at all.
  It is **WMO code table 4680 (wawa)**, and `0` ("no significant weather") is a real value, not missing.
  It carries **no cloud cover**, so it cannot give a sky condition on its own.
- **Five present-weather sensors report precipitation that is not falling, so the ladder ignores their precipitation codes** (`Station.untrusted_precipitation_codes`, #74).
  They are 11898 Banská Bystrica, 11949 Spišské Vlachy, 11893 Žabokreky, 11857 Turzovka and 11878 Liptovský Mikuláš, all non-synoptic.
  Measured live 2026-10-15 over a month of snapshots, they reported precipitation in 29–48 % of snapshots against ≤ 9 % at the other 29 `stav_poc` stations. The radar showed an echo in only 6–17 % of those reports, and their own gauge was wet in 1–4 %.
  Their code **0 is sound** (an echo ≥ 20 dBZ at under 2 % of them, as elsewhere), so it still vetoes the model's rain.
  `explain_condition(trust_precipitation_codes=False)` drops a precipitation code as if none had been reported, so the radar rung and the station's own gauge decide, as at a station without a code.
  The `weather_code` sensor still publishes the raw code, and diagnostics show the dropped one as `derived_condition.ignored_weather_code`.
  Re-measure before adding or removing a station. `tests_e2e` fails only if a flagged station stops reporting `stav_poc`, because over-reporting cannot be seen in one snapshot.

### Condition and stations

- **The condition comes from a cross-source priority ladder** (`resolution.py`), because no single source is complete.
  Each source emits candidates tagged with a priority, and the highest wins: observed present weather (website `Počasie`, then `stav_poc`), the radar, observed sky (website `Oblačnosť`), then the **ALADIN current-hour cloud cover**. `stav_poc` *distant* lightning is a last resort, and only the model's "clear sky" ranks below it, because that is the most easily wrong claim.
  The model fills a real gap: the website cloud column is **blank for most stations most of the time** (78 of 100 on 2026-06-05), so without it the condition went *Unknown* whenever the website and `stav_poc` were both silent.
  The winning source (`website`/`stav_poc`/`radar`/`aladin`) shows in diagnostics and in the entity's `condition_source`.
  **The model does not assert active weather over a contradicting observation**: a station reporting `stav_poc` 0 while dry vetoes the model's precipitation or storm candidate, and the ladder falls back to the model's cloud-only sky.
  ALADIN over-predicts convective cells, so it would otherwise show a phantom *lightning-rainy* on a dry summer afternoon (verified live 2026-06-11).
- **The radar is the ladder's precipitation observation for stations without a present-weather code** (#75).
  A study on 2026-10-15 scored a month of hourly live snapshots against 29 stations' own `stav_poc`: an echo ≥ 20 dBZ within ~1 km (3 px) of the station in the newest `zmax` frame scores HSS 0.58, against 0.26 for ALADIN. Two frames or a wider disc scored worse.
  ALADIN's weakness is where it puts showers, not the run's age: lead 3–4 h scores no better than lead 9–10 h.
  For a station without its own code, the radar rung plus a radar-dry veto of the model takes the ladder from HSS 0.35 to 0.58. When the model says rain over a radar-dry pixel, the station is precipitating 5–7 % of the time, against 30 % without the check.
  The radar rung (`_P_RADAR`, 75) sits below the station's own `stav_poc` (78) and above the website cloud (60), because the station observes the *type* at its own point while the radar sees only reflectivity overhead. A quiet station drops an echo, as it vetoes the model.
  A "quiet" station means `stav_poc` 0–3 with a gauge reading of zero. Reserved codes, 20–29 (the preceding hour) and a code 0 without a gauge reading say nothing about now.
  An echo is typed rain, sleet or snow by temperature (`forecast.precipitation_kind`), never as heavy rain or thunder. No `stav_poc` 90–99 occurred in the month, so thunder could not be scored.
  When the echo confirms a model *pouring* or *lightning-rainy* and the temperature says rain, the model's severity stays.
  We sample the echo **at the station** (`echo_at` in `async_get_radar`), not at the measurement location the radar picture is centred on, because the study validated station pixels and the ladder pairs the echo with the station's own weather and temperature.
  A frame reaches the listing 5–8 min after its nominal time, so the newest frame is at most ~14 min old when read. `RADAR_ECHO_STALE_AFTER` (20 min) adds one poll so a single failed radar fetch does not flap the condition, and `tests_e2e` pins coverage and a newest frame ≤ 15 min old.
  No station pixel was ever `nodata` in the month, which `tests_e2e` relies on. `local_echo` still returns `None` for no coverage, which means neither rain nor a veto.
  **Re-check in winter**: snow reflects less, so 20 dBZ may miss light snow (the study suggests 15 dBZ at T ≤ 1 °C). Score thunder against codes 90–99 next summer.
- **The website table is an hourly product, and we drop a held scrape after one hour** (verified live 2026-10-13).
  Its `<caption>` reads `Aktuálny stav počasia - DD.MM.YYYY - HH:00 LSEČ` (local summer time) and switches about two minutes past each hour, so the page is up to ~1 h behind. The HTTP `Last-Modified` is the CDN render time, not the report time.
  **The table fills in after the switch.** Polled on 2026-11-05, it first listed only 23–26 stations, nearly all synoptic, and all 99 rows from about five minutes later. The cloud cells fill in over the same minutes.
  So `test_website_conditions` asserts the full catalogue only from minute 15 on, and the synoptic stations at any time. The integration holds such a short table for a poll or two at most, and the missing rows rarely carry a condition anyway.
  A failed scrape keeps the previous snapshot, and the website outranks every other source. So `ShmuData.explain_condition` leaves out a snapshot whose `fetched_at` is older than `WEB_CONDITIONS_STALE_AFTER` (1 h), and the ladder falls through to `stav_poc` and ALADIN. Diagnostics flag it as `web_conditions.ignored_as_stale`.
  The age counts from our last successful scrape, not from the caption, which the scraper does not parse. If the page ever stalls while still answering, a parsed caption time would be the stricter test.
- **The station catalogue is hard-coded** (`stations.py`), because SHMÚ publishes none in machine form (#71).
  It lists every `aws1min` station that can be placed on a map (94 of 96) plus the synoptic Sliač, with `Station.synoptic` marking the 27 synoptic ones. The sources and the recipe are in the `stations.py` docstring.
  Verified live 2026-10-15:
  - **The id set is stable**: one file per day across the 30-day archive carried the same 96 `ind_kli`, though a day's file can miss a few stations.
    The `?page=838` map gives coordinates for all but Chopok and Lomnický Štít (synoptic, so `?page=318` covers them), Holíč (11800), Oravice (11919) and Jakubovany (11963). No source gives coordinates for Oravice and Jakubovany, so they are left out.
    The map also lists Bratislava - Mlynská Dolina (11810), which is absent from the feed and therefore left out.
  - **Sliač (11903, synoptic) was absent from the feed all 30 days**, though still on the map, in OSCAR and on the website table.
    It stays in the catalogue because existing config entries refer to it, and the coordinator asserts that an entry's station exists.
    `in_feed=False` keeps it out of the config flow and `nearest_station`. `tests_e2e` fails if it reports again, so the flag gets flipped back.
  - **Elevation comes from WMO OSCAR/Surface**, because SHMÚ publishes none for non-synoptic stations (searched: `climate/now/metadata/`, `?page=317`/`308`/`310` and the per-station `?ii=` page).
    OSCAR's coordinates equal the `?page=838` map's to six decimals, and its synoptic elevations agree with `?page=318` to a median 1 m. We use a record only on an exact coordinate match, except Holíč, which is matched by name and takes OSCAR's coordinates too.
    OSCAR lacks most of SHMÚ's eastern regional stations, so **26 stations have `elevation=None`**.
  - **ALADIN orography is no substitute for a missing elevation**: at stations with a known one, the nearest grid point's terrain misses by a median 46 m and up to 777 m (Lomnický Štít), about 5.6 and 94 hPa after reduction to sea level.
  - **Non-synoptic stations report unevenly**: in one snapshot all 70 report `t`, `vlh_rel` and wind, 69 report `zra_uhrn`, and only 19–28 each report `sneh_pokr`, `tlak`, `zglo`, `stav_poc` or `dohl`.
  - **The website table has a row for all 96 ids, but its condition columns barely cover them**: `Oblačnosť` was filled for 20 of 27 synoptic rows and 2 of 73 others, `Počasie` for 3 and 0.
    So a non-synoptic station's condition comes from `stav_poc` where it reports one, and otherwise from the radar and ALADIN.

  `tests_e2e` pins that the catalogue still reports and that the feed carries no more than a couple of ids the catalogue lacks.
- **Sea-level pressure is borrowed from a neighbour where a station cannot compute its own, and nothing else is** (`borrowing.py`, `BORROW_RULES`, #72).
  Over 31 daily snapshots (2026-10-15), the QFF of two stations below 1000 m differs by a median 0.3–0.7 hPa at any distance up to 100 km, so the error is each station's own reduction bias rather than distance. With one station at or above 1000 m, the difference roughly doubles.
  Hence the rule: a source within 40 km and below 1000 m, nearest first. 52 of the 54 feed stations without their own QFF have one.
  A neighbour lends only from a snapshot acquired within `OBSERVATION_STALE_AFTER`, and only if its record keeps up with that snapshot's newest (`_reading_is_current`, shared with the rain gauges). Unlike the station's own reading, a borrowed one is never carried forward.
  The two bounds add up, so a borrowed reading can be up to ~60 min old, against ≤ 30 min for the station's own. For a quantity that changes by a few hPa a day, that is well inside the borrowing error.
  The sensor's `source_*` attributes name the lender, and diagnostics show it under `sea_level_pressure`.
  The radar study (#75) found nothing else worth borrowing. A neighbour's 1-minute `zglo` differs by a median 18–21 % at 5–40 km, against 5 % between a station's own readings 4 minutes apart. A neighbour 10–20 km away reports fog in only 5 % of the target's fog hours. A neighbour's `stav_poc` beats ALADIN only within 20 km, and the radar subsumes it. Its code 0 is no dry veto either: 16 % of such hours were still precipitating.
  Any other reading needs its own measurement before it joins `BORROW_RULES`. Snow depth awaits a winter one.

### ALADIN forecast

- **The ALADIN files are GRIB2 in a narrow encoding that we decode ourselves** (`weather/nwp/aladin/sk/4.5km/YYYYMMDD/{0000,0600,1200,1800}/al-grib_sk_NNN-…-nwp-.grb`, verified live 2026-05-17).
  Forecast fields use **Section 5 DRT 5.0 simple packing** (`nbits` 8/12/16), and hour `000` also carries the constant orography as one **DRT 5.4 IEEE float** message. `grib2.py` decodes both and raises on anything else, so no C codec is needed.
  The grid is **fixed**: Lambert conformal conic, Nx=94 Ny=48, Dx=Dy=4500 m, La1=47.74175 Lo1=16.849607, LaD=Latin1=Latin2=46.2447, LoV=17.0, spherical R=6 371 229 m, scan `0x40`, with a Section-6 **bitmap** (2479 of 4512 points active).
  The grid-definition-template octet reads `33`, which is no standard template, but the 3.30 Lambert layout decodes correctly. Treat it as an encoder quirk of this one immutable grid.
  Each hour-file carries the surface fields we need: `2t` (0,0,0@103), `10u/10v` (0,2,2/3@103), gusts (0,2,23/24@103, pdt 8), precipitation over the past hour (0,1,193@1, pdt 8), TCC (192,128,164@1), LCC/MCC (192,128,186/187@1), PRMSL (0,3,1@101) and CAPE (0,7,6@1).
- **Each file's precipitation message holds one hour, not a total since the run started** (verified live 2026-11-26, #104).
  Section 4 of `(0,1,193)` is template 4.8, an accumulation over a single 1-hour range ending at the file's valid time.
  We used to subtract consecutive files, which kept only the hours where the rate rose and served about a tenth of SHMÚ's forecast (#103).
  `parse_forecast` reads each step's window from its own message (`Grib2Message.statistic`) and raises unless it is an accumulation over exactly that hour, because a running total would be counted again by every step it overlaps. `tests_e2e` pins the one-hour window.
  Every step covers one hour, so `derive_condition` reads its amount directly as a rate in mm/h.
- **The forecast unpacks only its own grid point**, never a whole grid (#64).
  A simple-packed value sits at bit `index × nbits` of Section 7, and a grid point's `index` there is the count of set bitmap bits before it, so `Grib2Message.value_at` reads one value directly. A live run takes 12 ms this way, against 6.2 s unpacking every grid.
  Every message is still parsed and validated (template, bitmap, Section 7 length), so the fail-loud contract does not depend on which path reads a file.
  `iter_fields` still unpacks whole grids for tests and tooling. Keep the forecast off it.
- **Runs do not all reach the same horizon** (verified 2026-08-26 across the 32-day retention, #45).
  Only the **00 UTC** run publishes hours **000–102** (103 files). The **06/12/18 UTC runs stop at +72 h** (73 files).
  Requiring +102 from every run once discarded three runs in four, so the forecast refreshed once a day.
  `MIN_FORECAST_HOURS` (+72) is the bar a run must clear, and the client takes the run's **contiguous leading run of published hours**. A hole still disqualifies the run, because each file holds only its own hour's precipitation and a missing file would drop that hour's rain.
  We fetch every published hour, out to `FORECAST_HOURS` (102), the product's own horizon.
  Don't thin the files to save download volume: reading only every third file past +48 h once dropped two hours of rain in three.
  The final local day is therefore almost always truncated (hour 102 of a 00 UTC run lands ≈08:00 local), so `weather._aggregate_daily` emits a day only when the horizon reaches its local end of day. Today needs no such guard, because its only missing hours are in the past.
- **`coordinator._merge_forecast_runs` keeps a series across runs**, because a single run is short at both ends.
  A run starts at its reference hour, so it can omit today's earlier hours (a 06 UTC run starts ≈08:00 local, past the dawn minimum). A +72 h run also ends before its last local day does, so `_aggregate_daily` would drop that day.
  The merge keeps one step per valid time, newest run winning, so the previous snapshot fills what the newest run lacks: today's earlier hours at the head and the 00 UTC run's longer reach at the tail.
  It then bounds the series to the current local day on every cycle, not only on a run change, so yesterday drops at midnight even while the run is unchanged.
  The forecast stays purely model-sourced: we never fold in observations. Each `ForecastStep` records its `run`, and the snapshot's `run`/`source` name the newest contributing one.
  **The merge assumes interleaved steps still tile**, each precipitation window meeting its predecessor exactly. That holds because every run is hourly, but it is not guaranteed, so `ForecastStep.span_hours` keeps each window's width and `_accumulations_tile` checks it.
  If the spacing ever changes, we fall back to the newest run alone rather than double-count rain. The fallback logs, shows in diagnostics as a sole `contributing_runs` entry equal to `run`, and is re-evaluated every cycle.
- **The hour-files also carry upper-air fields**, and we parse and validate every message whether or not we read it (verified 2026-08-26 across six files of three runs, #48).
  Each file has 36 messages, 25 of them on pressure levels 925/850/700/500/250 hPa: temperature (0,0,0), relative humidity (0,1,1), `u`/`v` (0,2,2 / 0,2,3) and geopotential (0,3,4), all DRT 5.0 on the same grid and bitmap.
  **`(0,3,4)` is geopotential in m² s⁻², not geopotential height** (WMO 4.2-0-3: 4 = geopotential, 5 = geopotential height). Divide by g₀ = 9.80665 for metres, or 850 hPa lands at 15 000 m. The hour-000 orography `(0,3,5)` is geopotential height in gpm.
  `param` carries the level type but not its value, so `Grib2Field.level` carries the first fixed surface's value and `forecast.py` keys fields by `(*param, level)`.
  Those keys match by float equality, which is safe because `_fixed_surface` divides any scale back out and every live level decodes to an exact integer-valued float.
  **The risk is a level that stops decoding to the constant** (a changed level set, or a scaled value with no exact binary form), because the field then goes missing silently rather than raising.
  The `tests/test_forecast.py` check that every surface field is non-None guards our own constants. An upstream change shows up only in production, as a sensor going unavailable or a `null` in the diagnostics `current_step`.
  **Pressure levels below the model terrain hold extrapolated values** (at a Chopok grid point, 925 hPa sits underground), so `forecast._vertical_profile` drops them before interpolating a 0 °C crossing.
  **Hour 000 carries no precipitation message**: orography takes its slot, and the run's first hour of precipitation is in hour 001's file.
- **We surface only the 850 hPa temperature and a freezing level, both as opt-in sensors**, because they are model output that most households never need. Relative humidity and the upper winds are validated but never unpacked.
  The freezing level is the 0 °C isotherm in m above sea level, derived only from a profile anchored at the 2 m temperature over the hour-000 terrain. Without the ground, a sub-zero 925 hPa point would pose as the surface, so unknown is the honest answer there.
  Its accuracy follows the profile's spacing: good below 850 hPa, where winter freezing levels sit, but a few hundred metres out in summer, inside the ~2.6 km 700→500 hPa gap.
  It is **not the snow line**, which sits some way below the isotherm because snow keeps falling while it melts. Don't let user-facing text equate the two.
  `derive_condition` does not use the profile. Calling a warm-nose-aloft setup *snowy-rainy* would change visible conditions on a heuristic no August data can confirm, so revisit it against a live winter case.
- **SHMÚ's metadata (`weather/nwp/metadata/OpenData_AladinSHMU_metadata.json`) labels `tcc` "vysoká oblačnosť" (high cloud), but the files hold no high-cloud message.** `192,128,164` is total cloud cover, as `grib2.py` decodes it. Trust the message inventory, not the label.

### Warnings

- **Warnings are CAP 1.2 XML**, and we prefer the Slovak `<info>` block and test a point against the alert's polygons.
  Every `HHMM/` issuance folder republishes the **full** active set, multi-day warnings included (verified 2026-05-17), so reading only the newest issuance of the newest day is correct.
  If warnings ever flip off while still in force, SHMÚ may have switched to incremental issuances. Re-check that the newest issuance still holds warnings whose onset predates today, and that the identifier sets of the last two issuances are about equal, not disjoint.
- **An empty `cap/` root is a valid state, not an outage** (verified live 2026-10-13, #55).
  Once the last alert expires, SHMÚ prunes the day folders and publishes no empty issuance in their place.
  `async_get_warnings` returns an empty snapshot only for a listing with no entries at all. Entries that are not `YYYYMMDD/` folders still raise, since they mean the layout changed.
- **SHMÚ writes an issuance over several minutes, so a poll can list only part of it** (verified 2026-11-26 over the whole archive, #101).
  Since 2026-11-24 most issuances took 2–5 minutes to write, and the files are not written in name order, so a partial listing is a random subset of the alerts.
  An issuance folder's own `Last-modified` equals its newest file's, so no file arrives after the writing ends.
  `async_get_warnings` lists the served issuance on every poll and reads only the files new since (`WarningsSnapshot.files`).
  A newer issuance replaces it only once two polls in a row list the same files (`pending_source`/`pending_files`), and never while it lists none. A new issuance is therefore served 5–10 minutes after SHMÚ finishes it, and a half-written one never hides alerts still in force.
  With no alerts to keep serving (on the first poll, or after an empty root), we read a new issuance at once and let it grow over the next polls.
  Issuances sometimes follow each other within minutes, and the newest one then restarts the wait.
  A fixed wait after the folder's `Last-modified` would have to cover the longest write and compare SHMÚ's clock with ours, so we don't use one.
- **Each alert covers one warning region, and Piešťany's alerts carry no polygon** (verified 2026-11-26 over the whole archive, #102).
  Every alert has exactly one `<area>`, named by an `EMMA_ID` geocode for one of 72 regions: the districts, with the city districts of Bratislava and of Košice merged into one region each.
  The other 71 regions always send a `<polygon>` (with `use_polygon_over_geocode` set to `True`), identical across their alerts. Piešťany (SK204) sent none in any of its alerts.
  `Warning.covers()` treats an alert without polygons as country-wide, and the parser used to pass Piešťany's alerts on without any, so they matched every location in Slovakia (#99).
  The parser now outlines such an area by its region from `regions.py`, which holds all 72 regions so the fallback works for any region whose polygon goes missing.
  We generate `regions.py` from the district map on SHMÚ's own warnings page (`www.shmu.sk/assets/maps/meteo_map.json`, recipe in the module docstring). That map's `ID` is not the `EMMA_ID`, so a map feature is matched to an alert by the district abbreviation that ends the alert's `<identifier>`.
  The map's boundaries differ from the CAP polygons by a median 90 m, except around Kežmarok, whose CAP polygon takes in about 200 km² that the map gives to its neighbours.
  An area with neither a polygon nor an outline in `regions.py` makes the parser reject its alert, which the client logs and skips, because covering the whole country would repeat #99. `tests_e2e` fails on such a skip, and when any alert names a region that `regions.py` lacks.
  Neighbouring regions' CAP polygons overlap in slivers along their boundaries, so a point right on one can get both regions' warnings.
  Every station and rain gauge lies in exactly one region, by the CAP polygons and by `regions.py` alike, and both keep the city of Košice, a region of its own, out of Košice okolie.
- **SHMÚ issues most warnings before they come into force** (verified 2026-11-26 on the last issuance of six days across the archive, #PR).
  Every one of those issuances held alerts whose `onset` lay after the issuance was sent, 245 of 452 in all, by a median 8 h and up to 67 h.
  `Warning.is_active` is false for them, so the binary sensor and the warning level leave them out, and only the calendar shows them (`ShmuData.unexpired_warnings_for`).
  Every alert carried both `onset` and `expires`. The calendar leaves out an alert without them rather than invent a span, and `tests_e2e` fails if one appears.
  Re-check if the calendar stays empty while SHMÚ's warnings page shows warnings for the next day.

### Radar

- **The radar composite is ODIM_H5 2.1 in a narrow HDF5 subset that we decode ourselves** (`weather/radar/composite/skcomp/<product>/YYYYMMDD/`, a new file every 5 min, ~32 days kept, verified live 2026-05-17 across all four products, #6).
  `zmax` and `cappi2km` carry **`DBZH`** as `u8` (gain/offset dBZ, with raw `0` = no echo and `255` = outside coverage), `etop` carries `HGHT` as `u8`, and `pac01` carries `RR`/`ACRR` as little-endian **`f32`**.
  The files use HDF5 **superblock v0**, 8-byte offsets, classic symbol-table groups with a local heap, **v1 object headers (16-byte prefix = 12 + 4 pad)**, and a **single deflate chunk** spanning the whole 2270×1560 grid.
  The projection is Mercator (`+proj=merc +lon_0=18.7 +lat_ts=48.43 +ellps=sphere`), with corner lat/lon in `/where`.
  The vendored `odim.py` decodes exactly this subset and raises on anything else, the same contract as `grib2.py`. `radar.py` renders a palette PNG with stdlib `zlib` only, so there is no h5py or Pillow, for the same no-binary-deps reason.
  If a radar read starts failing, re-verify one file's HDF5 structure against this list before changing the reader.
- **Each frame is rendered twice, and the map rendering has a geometric contract** (#51).
  `radar.py` takes a `RadarStyle`: `STATION_VIEW` crops to ~150 km, stride-samples to ≤ 760 px and draws borders, marker and timestamp, while `MAP_OVERLAY` keeps the whole grid at native 2270×1560 with no decoration.
  The client decodes each ODIM file once and renders both (`client._render_frame`) in a worker thread, since that pair is the radar poll's only heavy CPU work. `async_get_forecast` likewise runs `parse_forecast` in a worker thread despite its 12 ms, because parsing the headers of ~67 files is still real work and any whole-grid read (`iter_fields`) would take seconds. Keep any new per-run decode off the event loop too.
  A Leaflet card (`ha-map-card`, with our plugin `frontend/radar-map-overlay.js` served from `/shmu_static/` by `_async_register_frontend`) stretches the picture linearly between the reported corners in Web Mercator.
  The grid is spherical Mercator (`geo.py`), so the two agree **exactly**: 0 px of error across the whole grid against Leaflet 1.9.4 on a live composite, pinned offline by `test_overlay_lands_where_a_web_map_puts_it`.
  The reported box is the span **actually drawn** (`col0 + out_w * step`), not the requested crop, because under stride sampling the two differ by up to `step - 1` source pixels, a constant offset on the ground.
  A map loop is spliced with `progress=False`, because the step markers are drawn in pixel space and would land in the terrain and stretch with the zoom.
  A map loop shows no time: the browser plays the APNG itself, so nothing on the page knows which frame is on screen. A proper fix needs the plugin to own the animation from per-frame URLs (#52). Don't infer the frame from local timing, since a background tab throttles the animation and the label would drift.

### Deliberately unused

- **Three further trees are unused on purpose** (surveyed 2026-08-26).
  `climate/recent/data/daily/` publishes monthly daily-climate files that lag 2–3 months, so it is an archive rather than a live source.
  `products/grids/climateAdaptation/` holds static GIS ZIPs of climate normals and scenarios.
  `weather/radar/volume/{skjav,skkoj,skkub,sklaz}/` holds per-site dual-polarisation polar volumes, far heavier than the composite we render and no gain on a home dashboard.
- **Only ALADIN is published as data**: `weather/nwp/` contains exactly `aladin/sk/4.5km/` (verified 2026-08-26).
  SHMÚ runs ECMWF to 8–10 days and the A-LAEF ensemble but publishes both only as rendered images on the website, so a longer or probabilistic forecast is out of scope.
  Re-check `weather/nwp/` before concluding that an ensemble is unavailable, since that is where it would appear.
- **Air quality is out of scope**: `airQuality/` serves no data files, only Windows `.url` shortcuts to the EEA download webapp or to INSPIRE records on `rpi.gov.sk`, plus a `.docx` how-to (verified 2026-05-17, re-verified 2026-08-26).
  Consuming it would need the EEA portal or scraping, both against the project's constraints. Don't add an air-quality source without revisiting that decision.
