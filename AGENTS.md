# AGENTS.md

Guidance for AI coding agents working in this repo. Read this before changing
data-fetching or condition logic — it records the non-obvious constraints
learned by reverse-engineering the SHMÚ source.

Setup, the pre-push quality gate, and the general contributor ground rules
(the vendored-library boundary, offline-deterministic tests, TLS handling,
scraper isolation) are in [CONTRIBUTING.md](CONTRIBUTING.md) and are **not
repeated here**. `CLAUDE.md` is a symlink to this file for tool compatibility.

## Markdown: don't hard-wrap prose

Write Markdown prose one sentence (or list item) per line — do **not** wrap it to a column width. Line-length limits apply to *code* only (enforced by `ruff`; the value lives in `pyproject.toml` — don't infer a number from this note or apply it to prose). Column-wrapping Markdown splits real sentences, and GitHub renders single newlines in release notes / issue / PR bodies as hard line breaks. `CHANGELOG.md` is the live example: `release.yml` feeds its `## [x.y.z]` section verbatim into the GitHub Release, so column-wrapped entries show ragged mid-sentence breaks in the published notes. Let lines run long; wrap only between sentences if at all.

## The rule specific to this data source

**Verify upstream assumptions against the live server** before encoding them,
and document what you verified (see the dated notes under *Non-obvious
data-source facts*). Don't add speculative workarounds for failure modes that
don't occur.

## Layout

| Path | What |
|---|---|
| `custom_components/shmu/shmu_opendata/` | Vendored client library (no HA deps) |
| `custom_components/shmu/` | Home Assistant integration (the glue) |
| `tests/` | Fast offline library tests |
| `tests/components/` | HA integration tests (`pytest-homeassistant-custom-component`) |

- `manifest.json` `requirements` is **empty**: the vendored library is bundled
  and `aiohttp` ships with HA (the library is HACS-only by design, not on
  PyPI — see
  [Why HACS](CONTRIBUTING.md#why-hacs-and-not-home-assistant-core)).
- mypy strict-checks the vendored library **in isolation** (see
  `pyproject.toml` `mypy_path`), so it never imports the HA-dependent parent
  package.

## Non-obvious data-source facts

- **opendata.shmu.sk serves a broken TLS chain**: it sends only the leaf cert
  and omits the Sectigo intermediate ("Sectigo Public Server Authentication CA
  DV R36"). We bundle that intermediate
  (`custom_components/shmu/shmu_opendata/certs/`, fetched
  from the cert's AIA) and add it to a normal trust store. **Never** disable
  verification to "fix" a TLS error here — refresh the bundled intermediate.
- **It is a plain Apache file index**, no API. Finding the newest file means
  parsing an HTML directory listing; hrefs are percent-encoded.
- **Observations** (`climate/now/data/.../aws1min - ....json`): new file every
  5 min, ~95 stations, several 1-minute records each. Keyed by `ind_kli`.
- **The rain gauges are a second, disjoint station network** (`precipitation/now/data/.../aps1min - ....json`, new upstream on 2026-07-06): same envelope and 5-minute cadence as `aws1min`, ~32 days kept, but keyed by `ind_zra` and carrying only `zra_uhrn` (mm, 1-minute sum) and `t` (°C at 2 m, 1-minute average). ~70 KB per file, against ~390 KB for `aws1min`.
  **Verified live 2026-08-26**: ~1000 records from ~190 stations in one file, and the id set is *completely disjoint* from the 95 `ind_kli` AWS stations — a complementary network, not a re-cut of the observations we already fetch. It is roughly three times denser (~16 km spacing vs ~40 km), which is the whole point of using it: the nearest rain gauge is usually much closer than the nearest synoptic station.
  It is now **used**, for the `rain_gauge_precipitation` sensor (`gauges.py`, issue #43). The station's own `precipitation` sensor still reads `aws1min` — the two networks are deliberately kept as separate entities rather than one silently standing in for the other.
  **The gauge coordinates come from the website, not the open-data server**, which publishes none. `shmu.sk/sk/?page=838&uhrny=24` ("Úhrn zrážok") renders a Leaflet map whose marker list is an inline JS array in the page HTML, carrying `nazov`/`lat`/`lon`/`uid` — `uid` being `APS2<ind_zra>` (also `AWS2<ind_kli>` and `AHS<hydro id>` for the other two networks on that map). The exact regeneration recipe is in the `gauges.py` docstring. This is an *offline* regeneration step, not runtime scraping: `website.py` remains the only HTML-coupled runtime module.
  **Cross-validated 2026-08-26**: the same array's 94 `AWS2` entries include 24 stations already in `stations.py` (curated from a different SHMÚ page, `?page=318`), and the two independent sources agree to a **median 272 m, max 1.2 km** — far below the network's spacing, so the map's coordinates are genuine station positions.
  Two routes that look promising are **dead ends, both re-verified 2026-08-26** — don't repeat them: the INSPIRE record linked from `precipitation/` (`rpi.gov.sk/…/dfa31b86-…`) returns an *empty* `csw:GetRecordByIdResponse` from the RPI CSW (the record is not indexed), and the national open-data catalogue entry named in `aps1min_metadata.json` (`data.slovensko.sk/datasety/34c1c3ae-…`) carries exactly one distribution — the JSON feed itself.
  The catalogue is **near-complete, not total**: sampling the feed across its 32-day archive found 197 distinct `ind_zra` against the 190 the map page lists, so parsers must tolerate an id that is not in `gauges.py`.
  The feed also **mixes hours-old backfill in with the current minutes** (one snapshot spanned 8 hours), so only the newest record per gauge is meaningful — the same rule `parse_observations` already applies to `aws1min`.
  Worse, **a gauge's presence in a snapshot does not mean it is still reporting**: verified 2026-08-26 across the archive, gauge 32100 was absent from every snapshot of 2026-08-11 and then published 73 rows at once at 23:00 whose *newest* was 29 hours old (2026-08-10 16:44). A second case lagged 67 min. A day-old reading would otherwise be served as the current one and renewed indefinitely.
  Note that a *backfill dump advances*: those 73 rows step forward minute by minute, so "did this gauge's `measured_at` move forward since last poll?" accepts them and is **not** a sufficient test. The coordinator instead compares the gauge's newest record against the newest record **anywhere in the same snapshot** — that feed's own notion of "now" — and treats it as current only within `OBSERVATION_STALE_AFTER` of it. Sampled across the archive that separates cleanly: 99.8% of gauge readings sit within 10 minutes of their snapshot's newest, 0.14% are past 30 minutes, and the stragglers are hours behind.
  That test compares the gauge against **its own snapshot** rather than against the wall clock. `minuta` is now parsed correctly (see the next bullet), so an absolute age check would also work; the relative one is kept because it measures the thing that actually goes wrong here — a gauge falling behind *its own network* — and stays right regardless of the HA host's clock. It does not, on its own, catch the whole feed freezing; that is covered separately by only counting a snapshot whose source path changed.
  Also seen in the archive: an **empty** snapshot (`data: []`), so anything reducing over a snapshot must tolerate that.
- **`minuta` is SEC (fixed UTC+1), not UTC — and the file *names* are not.**
  Both feeds' metadata document the field as "termín merania v case SEC" / "time of observation SEC" (`climate/now/metadata/aws1min-metadata.txt`, `precipitation/now/metadata/aps1min_metadata.txt`); *SEC* = **stredoeurópsky čas**, the standard-time designation, so it means UTC+1 and not local summer time (which Slovak calls *SELČ*).
  **Verified live 2026-08-26** over the whole 32-day retention (20260726–20260826), one file per day: the newest `minuta` runs a constant **+0.97 h** ahead of the file's HTTP `Last-Modified` — i.e. exactly +1 h, less the ~2-minute publish lag — while the file *name* runs a constant **+2.00 h** ahead of it.
  So one file mixes two conventions: the name is local wall time (CEST that week) and `minuta` is an hour behind it.
  That is the discriminating observation for the DST question: the check ran **during** summer time, and `minuta` still read UTC+1, so it does **not** track local DST. (The archive keeps only ~32 days, so no winter file is ever in range to confirm the other half directly; fixed-UTC+1 year-round follows from the SEC label plus the fact that it already diverges from local time.) If `minuta` ever starts matching the file name, SHMÚ has switched to local time — re-run the `Last-Modified` comparison before trusting timestamps.
  `_parse_minuta` (`parsers.py`) attaches `_SEC` accordingly. **This was wrong until 2026-08-26**: the field was read as UTC, which put every observation an hour in the future. Ordering within a file was unaffected (all records share the offset), so the bug was invisible in "latest reading wins" — it surfaced only in the absolute value, via the weather entity's `observation_time` attribute.
- **`tlak` is station-level pressure (QFE), *not* reduced to sea level.**
  Verified 2026-07-21 on live data: Lomnický Štít (elevation 2635 m) reports
  `tlak` ≈793 hPa — the raw barometer reading at altitude, not the ~1013 hPa
  people associate with "air pressure". The forecast, by contrast, carries
  `PRMSL` (already reduced to MSL), so the two are on different datums. The raw
  value is surfaced as-is by the `pressure` sensor; `pressure.py`
  (`sea_level_pressure`) reduces it to QFF for the `sea_level_pressure` sensor
  and the weather entity's `native_pressure`, using the station's `elevation`
  and current temperature (the barometric formula with the ICAO lapse rate).
  The reduction needs a real temperature, so it returns `None` when either
  pressure or temperature is missing rather than guessing a headline value.
- `stav_poc` (present-weather code) is **per-station, not time-sparse**: only
  ~35/95 stations report it at all (≈16/27 synoptic). It is **WMO code table
  4680 (wawa)**; `0` = "no significant weather" is a *real* value, not missing.
  It carries **no cloud cover**, so it cannot yield a trustworthy sky
  condition on its own.
- **Condition** is resolved by a cross-source **priority ladder**
  (`resolution.py`), not a simple fallback chain — because no single source is
  complete. Each source emits candidate conditions tagged with a priority and
  the highest wins: observed present weather (website `Počasie`, then
  `stav_poc`) at the top, then observed sky (website `Oblačnosť`), then the
  **ALADIN current-hour cloud cover** filling the sky state the observations
  lack, with "clear sky" deliberately ranked low (it is the most easily-wrong
  claim) and `stav_poc` *distant* lightning a last resort just above unknown.
  The verified reason this matters: the website cloud column is **blank for
  most stations most of the time** (live check 2026-06-05: 78/100 empty), so
  without the model gap-filler the condition flipped to *Unknown* whenever both
  the website cloud cell and `stav_poc` were silent. The winning source
  (`website`/`stav_poc`/`aladin`) is surfaced in diagnostics and the entity's
  `condition_source`. **The model gap-filler does not assert active weather over
  a contradicting observation**: when a station reports `stav_poc` 0 ("no
  significant weather") and is dry, that vetoes the model's *precipitation/storm*
  candidate and the ladder falls back to the model's cloud-only sky state — ALADIN
  over-predicts convective cells, so on a dry summer afternoon it would otherwise
  surface a phantom *lightning-rainy* (verified live 2026-06-11). Scraping still
  means v1 ships via **HACS, not HA core**; `website.py` remains the only scraping
  module and is deliberately swappable.
- **Station catalogue** is hard-coded (`stations.py`); SHMÚ publishes none in
  machine form. Regenerate from `shmu.sk/sk/?page=318` (coords) +
  `?id=meteo_apocasie_sk` (names). 27 synoptic stations.
- **ALADIN forecast GRIB2** (`weather/nwp/aladin/sk/4.5km/YYYYMMDD/{0000,
  0600,1200,1800}/al-grib_sk_NNN-…-nwp-.grb`). **Verified 2026-05-17 on a
  live file** (Phase-2a spike #2, refined in Phase-2b #3): forecast fields
  use **Section 5 DRT 5.0 simple packing** (`nbits` 8/12/16); hour `000` also
  carries the constant orography as one **DRT 5.4 IEEE float** message — both
  are decoded (`grib2.py`), *no* JPEG2000/PNG/CCSDS, so no C codec is ever
  needed. Anything else raises loudly rather than mis-decoding. Grid
  is **fixed**: Lambert conformal conic, Nx=94 Ny=48, Dx=Dy=4500 m,
  La1=47.74175 Lo1=16.849607, LaD=Latin1=Latin2=46.2447, LoV=17.0, spherical
  R=6 371 229 m, scan `0x40`, with a Section-6 **bitmap** (2479/4512 active).
  The grid-definition-template octet reads `33` (no standard 3.33); the 3.30
  Lambert layout decodes correctly — treat the number as a known ALADIN
  encoder quirk and assume this one immutable grid. Each hour-file carries
  all needed surface fields: `2t`(0,0,0@103), `10u/10v`(0,2,2/3@103), gusts
  (0,2,23/24@103,pdt8), total-precip-accum(0,1,193@1,pdt8), TCC(192,128,
  164@1), LCC/MCC(192,128,186/187@1), PRMSL(0,3,1@101), CAPE(0,7,6@1).
  There are 4 runs/day but **they do not all reach the same horizon**: only the **00 UTC** run publishes forecast hours **000–102** (103 files, ≈161 KB each); the **06/12/18 UTC runs stop at +72 h** (73 files).
  **Verified 2026-08-26** across the whole 32-day retention — these are finished runs, not runs caught mid-publication.
  (An earlier note here claimed 103 files for all four; that generalised from a single 00 UTC run. The cost of believing it: the client required every requested hour through +102, so three runs in four were silently discarded and the forecast refreshed **once a day**, up to 24 h stale.)
  `MIN_FORECAST_HOURS` (+72) is therefore the bar a run must clear, and the client takes a run's **contiguous leading run of published hours** — a *hole* still disqualifies it, because precipitation is accumulated since the run start and a missing file would widen a step's window past its interval.
  **This +102 h is the product's own horizon, not a limit of our request** — we
  already fetch out to hour 102 (`FORECAST_HOURS`, the last file a 00 UTC run
  publishes). The consequence for the **daily** forecast: the final local
  calendar day is almost always truncated (for a 00 UTC run, hour 102 lands
  ≈08:00 local, i.e. before the afternoon temperature peak), so summarising that
  bucket would present a morning-only slice as a whole day (a Saturday "high" of
  the pre-dawn temperature). `weather._aggregate_daily` therefore emits a day
  only when the horizon reaches its **end of local day**, dropping the truncated
  tail; the leading day (today) needs no such guard because its only missing
  hours are already in the past. We also **subsample to 3-hourly past +48 h**
  (`range(51, 103, 3)`) to cut download volume — that is *our* choice and only
  lowers resolution *within* the covered days; it does not change the horizon.
  Because those later steps are 3-hourly, `derive_condition` classifies
  precipitation by **per-hour rate** (`hours` arg), not the raw step total, or a
  drizzle spread over three hours reads as *pouring*. A longer daily horizon
  would need a longer-range model (SHMÚ runs ECMWF to 8–10 days) but SHMÚ
  publishes ECMWF **only as rendered meteogram images** on the website, not as
  open GRIB2 in the `opendata` tree — so it is out of scope for the same
  data-only reason as air quality.
  **A single run is short at both ends**, which is why `coordinator._merge_forecast_runs` keeps a *series* rather than the newest run's steps.
  At the **leading** edge, a run begins at its reference hour (00/06/12/18 UTC), so it can start partway through the current local day and omit today's earlier hours (a 06 UTC run first covers ≈08:00 local, past the dawn minimum) — today's high/low would then be computed from a partial day.
  At the **trailing** edge, a +72 h run's horizon falls short of its last local day's end (end of local day is 22:00 UTC under CEST, 23:00 under CET), so `_aggregate_daily` would drop that day: using a fresh short run *alone* costs a whole forecast day, whatever hour it was issued.
  Rather than fold in observations (which would mix an observed station reading into a model, location forecast), the merge keeps one step **per valid time with the newest run winning**, so whatever the newest run does not cover survives from the previous snapshot — today's earlier hours at the head, the 00 UTC run's longer reach at the tail — then bounds the result to the current local day (so a day rolling over drops yesterday even while the run is unchanged; that trim must run every cycle, not only on a run change).
  The forecast stays purely model-sourced; each `ForecastStep` records its originating `run`, and `run`/`source` keep identifying the newest contributing one.
  **The merge rests on an assumption**: that every run's step times are a subset of any denser run overlapping them.
  That holds for today's grids (a +72 h run's last step lands on 00 UTC hours 78/84/90, all members of `range(51, 103, 3)`), so each step's precipitation window still meets its predecessor exactly.
  It is an observation about the current product, not a guarantee — so `ForecastStep.span_hours` retains each window's width and `_accumulations_tile` checks it.
  If SHMÚ ever changes the spacing we **opt out of the merge** (falling back to the newest run alone, losing the extra day) rather than silently double-count rain; the fallback logs, shows in diagnostics as a sole `contributing_runs` entry equal to `run`, and is re-evaluated each cycle so a return to tiling grids recovers on its own.
- **The ALADIN hour-files also carry upper-air fields, and we decode every message whether or not we read it.** **Verified 2026-08-26** across hours 000/001/048/072 of the 06 UTC run, hour 102 of the 00 UTC run and hour 000 of the 12 UTC run: 36 messages each, of which **25 are pressure-level** at 925/850/700/500/250 hPa — temperature (0,0,0), relative humidity (0,1,1), `u`/`v` (0,2,2 / 0,2,3) and geopotential (0,3,4), all DRT 5.0 simple packing on the same grid under the same single bitmap (issue #44).
  `(0,3,4)` is **Geopotential, m² s⁻²** — *not* geopotential height in gpm, whatever a parameter table's shorthand suggests (WMO 4.2-0-3: 4 = Geopotential, 5 = Geopotential height, 6 = Geometric height).
  Divide by g₀ = 9.80665 to get metres; taking it as gpm puts 850 hPa at 15 000 m.
  The hour-000 orography `(0,3,5)` *is* geopotential height in gpm, which is why it reads as a plain terrain height.
  Reaching the pressure levels needed no new decoder, only a way to *address* them: `param` carries the level **type**, not its **value**, so all five same-quantity messages collapsed onto one key.
  `Grib2Field.level` now carries the first fixed surface's value and `forecast.py` keys fields by `(*param, level)`.
  Those keys match by float equality, which is safe because every live message has scale factor 0 and the decoded levels are therefore exact integers-as-floats (a *scaled* encoding is not automatically a problem — `_fixed_surface` divides the value back down, and e.g. `850000` scaled by 1 still decodes to exactly `85000.0`).
  The re-verification trigger is narrower than "SHMÚ changed the encoding": it is a level that stops **decoding to the constant** — a changed level set, or a decimal-scaled value with no exact binary form — because the field then goes *silently* missing rather than raising.
  The `tests/test_forecast.py` regression test asserting every surface field is non-None guards that in *our* code (a mistyped constant); an upstream change can only show up in production, as a sensor going unknown or a `null` in the diagnostics `current_step`.
  **Pressure levels below the model terrain hold extrapolated values**: at a Chopok grid point (terrain 1501 m) the 925 hPa surface sits at 816 m, i.e. underground, so a vertical profile must drop them (`forecast._vertical_profile`) or a 0 °C crossing can be interpolated below the ground it is measured from.
  **Hour 000 carries no total-precipitation message** (orography takes its slot in the 36) — accumulation since the run start is trivially zero there; it is not a truncated file.
  What we surface is deliberately narrow: **850 hPa temperature** (the air-mass indicator) and a **freezing level** (0 °C isotherm, m above sea level, anchored at the 2 m screen over the terrain), both as **opt-in** sensors, because they are model output rather than measurements and most households will never look at them.
  Relative humidity and the upper winds are decoded and dropped on the floor, on purpose.
  The freezing level's accuracy follows the profile's spacing — good below 850 hPa, where winter freezing levels sit, but the 700→500 hPa gap spans ~2.6 km, so a summer isotherm interpolated inside it can be a few hundred metres out.
  It is the **0 °C isotherm, not the snow line** — snow keeps falling and melting below the isotherm, so the snow level sits some way under it; don't let user-facing text equate the two.
  It is derived **only from a surface-anchored profile** (hour-000 terrain + the 2 m temperature): without the ground, everything below the lowest pressure level is unobserved, so a sub-zero 925 hPa point would pose as the surface and hand back its own height — unknown is the honest answer there.
  `derive_condition` was **left alone**: the textbook win is calling a warm-nose-aloft setup *snowy-rainy* instead of *snowy*, but that changes user-visible conditions on a heuristic no August data can confirm — revisit it against a live winter case, not with synthetic profiles.
  SHMÚ's metadata (`weather/nwp/metadata/OpenData_AladinSHMU_metadata.json`) labels `tcc` "vysoká oblačnosť" (high cloud), but **no 188/HCC message exists in the files** — `192,128,164` is total cloud cover, as `grib2.py` decodes it. Trust the message inventory, not that label; there is no high-cloud field in this product.
- **Warnings**: CAP 1.2 XML; the Slovak `<info>` block is preferred; polygons
  are used for point-in-station relevance. **Verified 2026-05-17**: every
  `HHMM/` issuance folder republishes the *full* active set (not deltas),
  including multi-day warnings from earlier days — so reading only the newest
  issuance of the newest day is correct. If warnings ever flip off while still
  in force, SHMÚ may have switched to incremental issuances; re-verify with:

  ```python
  # newest issuance should still contain warnings whose onset predates today,
  # and ~all of yesterday's still-valid alerts. Compare identifier sets across
  # the last two issuance folders (expect them ~equal, not disjoint).
  ```
- **Radar** (`weather/radar/composite/skcomp/<product>/YYYYMMDD/`): national
  composite, **ODIM_H5 2.1** (HDF5), a new file every 5 min, ~32 days kept.
  **Verified live 2026-05-17** across all four products (issue #6). Products:
  `zmax`/`cappi2km` carry quantity **`DBZH`** as `u8` (gain/offset dBZ; raw
  `0`=no echo, `255`=outside coverage — the two sentinels), `etop` `HGHT` u8,
  `pac01` `RR`/`ACRR` as little-endian **`f32`**. Files use HDF5 **superblock
  v0**, 8-byte offsets, classic symbol-table groups + local heap, **v1 object
  headers (16-byte prefix = 12 + 4 pad)**, and the composite dataset is a
  **single deflate chunk** spanning the whole 2270×1560 grid. Mercator
  (`+proj=merc +lon_0=18.7 +lat_ts=48.43 +ellps=sphere`); corner lat/lon in
  `/where`. Decoded by the vendored pure-Python `odim.py` (this exact subset
  only — anything else raises loudly, same contract as `grib2.py`) and
  rendered to a palette PNG by `radar.py` (stdlib `zlib` only; **no** h5py /
  Pillow — same no-binary-deps reason GRIB2 libs were rejected). If a radar
  read starts failing, re-verify the HDF5 structure of one file against this
  list before changing the reader.
- **Each radar frame is rendered twice, and the map rendering is the one with a geometric contract.** `radar.py` takes a `RadarStyle`: `STATION_VIEW` (crop to ~150 km, stride-sample to ≤760 px, draw borders/marker/timestamp) and `MAP_OVERLAY` (whole grid, native 2270×1560, no decoration). The client decodes each ODIM file once and renders both (`client._render_frame`), in a worker thread — that pair is the poll's only heavy CPU work.
  **Measured on live data 2026-09-02** (12-frame backfill, Bratislava): first poll 4.5 s, a poll with no new frame 0.1 s (nothing re-rendered), resident buffer 1.2 MiB; map still 29 KiB and map loop 332 KiB, against 6 / 71 KiB for the station view.
  The map rendering exists so a Leaflet card (`ha-map-card`; our plugin lives at `frontend/radar-map-overlay.js` and is served from `/shmu_static/…` by `_async_register_frontend`) can zoom it — which makes its bounding box a **contract, not a hint**. A web map stretches the picture linearly between the reported corners in Web Mercator, and this grid is spherical Mercator (`geo.py`), so the two agree *exactly*: verified against real Leaflet 1.9.4 on a live composite — **0 px of error across the whole grid, corners included** — and pinned offline by `test_overlay_lands_where_a_web_map_puts_it`.
  A map loop therefore shows no time at all: the browser plays the APNG internally, so nothing on the page can tell which frame is on screen. Fixing that properly means the plugin owning the animation, which needs per-frame URLs (issue #52); do not try to infer the frame from local timing, as a background tab throttles the animation and the label would drift onto a wrong time.
  Two consequences to keep: the reported box is the span **actually drawn** (`col0 + out_w * step`), not the requested crop — under stride sampling those differ by up to `step - 1` source pixels, a constant offset against the ground — and a map loop is spliced with `progress=False`, because the step markers are drawn in pixel space and over a map would land in the terrain and stretch with the zoom.
- **Three further trees exist and are deliberately unused** (surveyed 2026-08-26). `climate/recent/data/daily/` publishes monthly `kli-inter - YYYY-MM.json` files of daily climate elements, but lags ~2–3 months (newest month 2026-05 was published 2026-07-29), so it is a quality-controlled archive rather than a live source. `products/grids/climateAdaptation/` holds static GIS ZIPs (1991–2020 standard normals, RCP4.5/8.5 scenarios). `weather/radar/volume/{skjav,skkoj,skkub,sklaz}/` holds per-site dual-polarisation polar volumes (`dBZ`, `dBuZ`, `V`, `W`, `ZDR`, `KDP`, `PhiDP`, `RhoHV`) — far heavier than the national composite we already render, for no gain on a home dashboard.
- **Only ALADIN is published as data.** `weather/nwp/` contains exactly `aladin/sk/4.5km/` (verified 2026-08-26). SHMÚ also runs **A-LAEF** (the 17-member ALARO ensemble, two runs a day, 3-day range) but surfaces it *only* as rendered epsgram and map images on the website — so it is out of scope for the same data-only reason as the ECMWF meteograms above. Re-check `weather/nwp/` before concluding that an ensemble is unavailable; that is where it would appear.
- **Air quality**: `airQuality/` exists but serves **no data files** — every leaf is a Windows `.url` shortcut to the EEA download webapp (`eeadmz1-downloads-webapp.azurewebsites.net`) or to INSPIRE records on `rpi.gov.sk` (verified 2026-05-17, issue #6).
  **Re-verified 2026-08-26**: the tree has since grown `historical/`, `recent/` and `products/{management,models,nmsko}` subtrees, but every leaf is still a shortcut (plus a `.docx` how-to) — more signposts, still no data.
  It is **out of scope**: consuming it would need the EEA portal or scraping, both against the project's constraints. Don't add an air-quality source here without revisiting that decision.
