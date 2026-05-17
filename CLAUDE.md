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
- **Phase 2**: ALADIN forecast. Only available as **GRIB2** (edition 2). No
  pure-Python GRIB2 reader exists (`pupygrib` is GRIB1 only); `grib2io`/`cfgrib`
  need a C library. A spike must decide grib2io-wheel viability vs. website
  meteogram fallback. This is the known gap that keeps v1 on HACS.
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
