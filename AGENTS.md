# AGENTS.md

Guidance for AI coding agents working in this repo. Read this before changing
data-fetching or condition logic — it records the non-obvious constraints
learned by reverse-engineering the SHMÚ source. This is the single source of
agent guidance; `CLAUDE.md` is a symlink to this file for tool compatibility.

## The 6 rules that matter most

1. **Two layers, one boundary.** `custom_components/shmu/shmu_opendata/` is
   the vendored, pure client library — it must never import `homeassistant`
   (kept swappable / extractable). The HA glue is the rest of
   `custom_components/shmu/`.
2. **Never disable TLS verification.** opendata.shmu.sk omits an intermediate;
   the fix is the bundled cert in
   `custom_components/shmu/shmu_opendata/certs/`, not `verify=off`.
3. **Tests stay offline and deterministic.** Mock HTTP (`aioresponses`); use
   fixture-derived snapshots for HA tests. Add fixtures, not network calls.
4. **Scraping is quarantined** to `website.py` (deliberately swappable for the
   Phase-2 ALADIN source). Don't spread HTML parsing elsewhere.
5. **Quality gate before done:** `ruff check`, `ruff format`, `mypy`,
   `pytest tests/` — all clean/green.
6. **Verify upstream assumptions against the live server** before encoding
   them, and document what you verified (see the CAP-issuance note under
   *Non-obvious data-source facts* below). Don't add speculative workarounds
   for failure modes that don't occur.

## Layout

| Path | What |
|---|---|
| `custom_components/shmu/shmu_opendata/` | Vendored client library (no HA deps) |
| `custom_components/shmu/` | Home Assistant integration (the glue) |
| `tests/` | Fast offline library tests |
| `tests/components/` | HA integration tests (`pytest-homeassistant-custom-component`) |

- The vendored library is **HACS-only by design** (not published to PyPI),
  pure Python with no Home Assistant imports — kept HA-free so it stays
  swappable and could be extracted to its own package if a HA-core path is
  ever pursued.
- `manifest.json` `requirements` is **empty**: the library is bundled and
  `aiohttp` ships with HA.
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
- **Condition source** is therefore the SHMÚ website table
  (`website.py`, scraped) first, `stav_poc` (`conditions.py`) as fallback.
  Scraping means v1 ships via **HACS, not HA core**. `website.py` is the only
  scraping module and is deliberately swappable (Phase-2 ALADIN replaces it).
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

## Roadmap

- **Phase 1 (this)**: current conditions + CAP warnings. Pure Python + scrape.
- **Phase 2 — done (issue #3)**: ALADIN daily & hourly forecast. Vendored
  pure-Python GRIB2 decoder (`grib2.py`, DRT 5.0 + 5.4, bitmap-aware) +
  fixed-grid Lambert forward projection & field map (`forecast.py`) +
  `ShmuClient.async_get_forecast` (newest *complete* run only; cache identity
  = run folder, so the ~11 MB GRIB2 set is fetched ≈4×/day, not per poll —
  decision rationale in the #2 spike comment). The weather entity exposes
  `FORECAST_DAILY|HOURLY`; forecast `condition` is model-derived (TCC + precip
  + CAPE), so the forecast path needs **no scraping** — `website.py` is now
  only the *current*-condition source. Still HACS-only (no `manifest.json`
  requirement; lib stays HA-free + offline-tested via trimmed `*.grb`
  fixtures). `grib2io`/`cfgrib` were rejected (PyPI sdist-only; no HAOS
  aarch64/armv7 wheels). The website meteogram remains an unused fallback.
- **Phase 3**: quality-scale polish, diagnostics, optional radar/air-quality.

## Dev commands

Setup, the pre-push quality gate, and the full ground rules live in
[CONTRIBUTING.md](CONTRIBUTING.md) — that is the canonical workflow doc; this
file is not duplicated there.
