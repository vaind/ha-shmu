# ha-shmu — project notes for AI assistants

Home Assistant integration for SHMÚ (Slovak Hydrometeorological Institute)
weather data. Read this before changing data-fetching or condition logic — it
records non-obvious constraints learned by reverse-engineering the source.

## Layout

- `custom_components/shmu/shmu_opendata/` — the SHMÚ client library, **vendored
  in** (HACS-only by design; not published to PyPI). No Home Assistant
  imports, pure Python — kept HA-free so it stays swappable and could be
  extracted to its own package if a HA-core path is ever pursued.
- `custom_components/shmu/` — the HA integration glue. `manifest.json`
  `requirements` is empty (the library is bundled; `aiohttp` ships with HA).
- `tests/` — fast offline library tests (no HA). `tests/components/` — HA
  integration tests (need `pytest-homeassistant-custom-component`).
- mypy strict-checks the vendored library in isolation (see `pyproject.toml`
  `mypy_path`), so it never imports the HA-dependent parent package.

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
- **Condition source** is therefore the SHMÚ website table
  (`website.py`, scraped) first, `stav_poc` (`conditions.py`) as fallback.
  Scraping means v1 ships via **HACS, not HA core**. `website.py` is the only
  scraping module and is deliberately swappable (Phase-2 ALADIN replaces it).
- **Station catalogue** is hard-coded (`stations.py`); SHMÚ publishes none in
  machine form. Regenerate from `shmu.sk/sk/?page=318` (coords) +
  `?id=meteo_apocasie_sk` (names). 27 synoptic stations.
- **ALADIN forecast GRIB2** (`weather/nwp/aladin/sk/4.5km/YYYYMMDD/{0000,
  0600,1200,1800}/al-grib_sk_NNN-…-nwp-.grb`). **Verified 2026-05-17 on a
  live file** (Phase-2a spike, issue #2): every field uses **Section 5 DRT
  5.0 simple packing** (`nbits` 8/12/16) — *no* JPEG2000/PNG/CCSDS — so a
  ~80-line stdlib decoder is sufficient and no C codec is ever needed. Grid
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

## Roadmap

- **Phase 1 (this)**: current conditions + CAP warnings. Pure Python + scrape.
- **Phase 2**: ALADIN forecast (GRIB2 edition 2). **Decided 2026-05-17
  (issue #2 spike): vendored pure-Python simple-packing decoder** — *not*
  `grib2io`/`cfgrib` (PyPI ships sdist-only, no HAOS aarch64/armv7 wheels;
  building needs a C toolchain HAOS lacks). DRT 5.0 confirmed on a live file
  (see data-source note above), so no C codec/`manifest.json` requirement and
  the library stays HA-free + offline-testable. Phase 2b: `grib2.py` decoder
  + Lambert forward projection (lat/lon→i,j, ~25 lines `math`, bitmap-aware)
  + field→`Forecast` mapping (FORECAST_HOURLY *and* DAILY; TCC gives a
  self-contained forecast condition, so scraping leaves the forecast path).
  Fetch once per model run (~11 MB, ≈4×/day), gated on a new-run-folder
  identity check like observations — *not* per coordinator poll. Website
  meteogram (PNG/prose, no structured endpoint) is fallback-only. Still
  HACS-only (current conditions still scrape via `website.py`).
- **Phase 3**: quality-scale polish, diagnostics, optional radar/air-quality.

## Dev commands

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv pytest pytest-asyncio aioresponses ruff mypy \
    pytest-homeassistant-custom-component
.venv/bin/ruff check custom_components/ tests/
.venv/bin/ruff format custom_components/ tests/
.venv/bin/python -m mypy
.venv/bin/python -m pytest tests/          # 50 tests, offline
```

Tests are deterministic and offline (HTTP mocked with `aioresponses`; HA
component stubbed with fixture-derived snapshots). Keep them that way.
