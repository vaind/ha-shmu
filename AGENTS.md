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
  164@1), LCC/MCC(192,128,186/187@1), PRMSL(0,3,1@101), CAPE(0,7,6@1). Runs
  cover forecast hours **000–102** (103 files/run, ≈161 KB each), 4 runs/day.
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
- **Air quality**: `airQuality/` exists but serves **no data files** — every
  leaf is a Windows `.url` shortcut to the EEA download webapp
  (`eeadmz1-downloads-webapp.azurewebsites.net`) or SHMÚ web pages (verified
  2026-05-17, issue #6). It is **out of scope**: consuming it would need the
  EEA portal or scraping, both against the project's constraints. Don't add an
  air-quality source here without revisiting that decision.
