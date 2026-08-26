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
- **The rain gauges are a second, disjoint station network** (`precipitation/now/data/.../aps1min - ....json`, new upstream on 2026-07-06): same envelope and 5-minute cadence as `aws1min`, ~32 days kept, but keyed by `ind_zra` and carrying only `zra_uhrn` (mm, 1-minute sum) and `t` (°C at 2 m, 1-minute average).
  **Verified live 2026-08-26**: 907 records from 186 stations in one file, and the id set is *completely disjoint* from the 95 `ind_kli` AWS stations — a complementary network, not a re-cut of the observations we already fetch.
  Unused because SHMÚ publishes **no coordinates** for these gauges: the only pointer is an INSPIRE record (`rpi.gov.sk/…/dfa31b86-…`, a client-side app whose CSW returned nothing usable), so adopting it means hand-building a second catalogue beside `stations.py` (issue #43).
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
  There are 4 runs/day but **they do not all reach the same horizon**: only the
  **00 UTC** run publishes forecast hours **000–102** (103 files, ≈161 KB each);
  the **06/12/18 UTC runs stop at +72 h** (73 files). **Verified 2026-08-26**
  across the whole 32-day retention — these are finished runs, not runs caught
  mid-publication. (An earlier note here claimed 103 files for all four; that
  generalised from a single 00 UTC run. The cost of believing it: the client
  required every requested hour through +102, so three runs in four were
  silently discarded and the forecast refreshed **once a day**, up to 24 h
  stale.) `MIN_FORECAST_HOURS` (+72) is therefore the bar a run must clear, and
  the client takes a run's **contiguous leading run of published hours** — a
  *hole* still disqualifies it, because precipitation is accumulated since the
  run start and a missing file would widen a step's window past its interval.
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
  data-only reason as air quality. **A single run is short at both ends**, which
  is why `coordinator._merge_forecast_runs` keeps a *series* rather than the
  newest run's steps. At the **leading** edge, a run begins at its reference
  hour (00/06/12/18 UTC), so it can start partway through the current local day
  and omit today's earlier hours (a 06 UTC run first covers ≈08:00 local, past
  the dawn minimum) — today's high/low would then be computed from a partial
  day. At the **trailing** edge, a +72 h run's horizon falls short of its last
  local day's end (end of local day is 22:00 UTC under CEST, 23:00 under CET),
  so `_aggregate_daily` would drop that day: using a fresh short run *alone*
  costs a whole forecast day, whatever hour it was issued. Rather than fold in
  observations (which would mix an observed station reading into a model,
  location forecast), the merge keeps one step **per valid time with the newest
  run winning**, so whatever the newest run does not cover survives from the
  previous snapshot — today's earlier hours at the head, the 00 UTC run's longer
  reach at the tail — then bounds the result to the current local day (so a day
  rolling over drops yesterday even while the run is unchanged; that trim must
  run every cycle, not only on a run change). The forecast stays purely
  model-sourced; each `ForecastStep` records its originating `run`, and
  `run`/`source` keep identifying the newest contributing one.
  **The merge rests on an assumption**: that every run's step times are a subset
  of any denser run overlapping them. That holds for today's grids (a +72 h
  run's last step lands on 00 UTC hours 78/84/90, all members of
  `range(51, 103, 3)`), so each step's precipitation window still meets its
  predecessor exactly. It is an observation about the current product, not a
  guarantee — so `ForecastStep.span_hours` retains each window's width and
  `_accumulations_tile` checks it. If SHMÚ ever changes the spacing we **opt out
  of the merge** (falling back to the newest run alone, losing the extra day)
  rather than silently double-count rain; the fallback logs, is visible as a
  single `contributing_runs` entry in diagnostics, and is re-evaluated each
  cycle so a return to tiling grids recovers on its own.
- **The ALADIN hour-files also carry upper-air fields we don't decode.** **Verified 2026-08-26** on the 06 UTC run, hour 006: 36 messages, of which **25 are pressure-level** at 925/850/700/500/250 hPa — temperature (0,0,0), relative humidity (0,1,1), `u`/`v` (0,2,2 / 0,2,3) and geopotential height (0,3,4), all DRT 5.0 simple packing on the same grid, so reaching them needs no new decoder in `grib2.py`, only a wider message selection (issue #44).
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
- **Three further trees exist and are deliberately unused** (surveyed 2026-08-26). `climate/recent/data/daily/` publishes monthly `kli-inter - YYYY-MM.json` files of daily climate elements, but lags ~2–3 months (newest month 2026-05 was published 2026-07-29), so it is a quality-controlled archive rather than a live source. `products/grids/climateAdaptation/` holds static GIS ZIPs (1991–2020 standard normals, RCP4.5/8.5 scenarios). `weather/radar/volume/{skjav,skkoj,skkub,sklaz}/` holds per-site dual-polarisation polar volumes (`dBZ`, `dBuZ`, `V`, `W`, `ZDR`, `KDP`, `PhiDP`, `RhoHV`) — far heavier than the national composite we already render, for no gain on a home dashboard.
- **Only ALADIN is published as data.** `weather/nwp/` contains exactly `aladin/sk/4.5km/` (verified 2026-08-26). SHMÚ also runs **A-LAEF** (the 17-member ALARO ensemble, two runs a day, 3-day range) but surfaces it *only* as rendered epsgram and map images on the website — so it is out of scope for the same data-only reason as the ECMWF meteograms above. Re-check `weather/nwp/` before concluding that an ensemble is unavailable; that is where it would appear.
- **Air quality**: `airQuality/` exists but serves **no data files** — every leaf is a Windows `.url` shortcut to the EEA download webapp (`eeadmz1-downloads-webapp.azurewebsites.net`) or to INSPIRE records on `rpi.gov.sk` (verified 2026-05-17, issue #6).
  **Re-verified 2026-08-26**: the tree has since grown `historical/`, `recent/` and `products/{management,models,nmsko}` subtrees, but every leaf is still a shortcut (plus a `.docx` how-to) — more signposts, still no data.
  It is **out of scope**: consuming it would need the EEA portal or scraping, both against the project's constraints. Don't add an air-quality source here without revisiting that decision.
