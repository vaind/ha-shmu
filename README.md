# SHMÚ Weather for Home Assistant

A Home Assistant integration for Slovak weather data published by the
**Slovak Hydrometeorological Institute (SHMÚ)**.

> **Status: Phase 1 — early version.** Current conditions and weather
> warnings. Forecast support is planned (see [Roadmap](#roadmap)).

## ⚠️ Disclaimer

- This is an **unofficial, community project**. It is **not affiliated with,
  developed by, endorsed by, or supported by the Slovak Hydrometeorological
  Institute (SHMÚ)** in any way. "SHMÚ" is used only to identify the data
  source.
- This is an **early version** under active development. Behaviour, entity
  names and data may change without notice between releases.
- The integration reads data from public SHMÚ endpoints that have no stable
  API contract; it can break if SHMÚ changes them.
- Provided **"as is", without warranty of any kind. Use at your own risk.**
  Do not rely on it for safety-critical decisions; always consult official
  SHMÚ channels for authoritative weather warnings.

## Features

- **Weather entity** — current conditions for a chosen SHMÚ synoptic station.
- **Sensors** — temperature, humidity, pressure, wind speed/gust/bearing,
  precipitation, snow depth, visibility (plus diagnostic ground temperature,
  global radiation and the raw weather code), and a warning-level sensor.
- **Weather warnings** — a binary sensor (with full alert details as
  attributes) that is on while a SHMÚ CAP alert covers your station, decided
  by the alert's own polygon.
- One shared, change-detecting fetch per cycle, aligned to SHMÚ's upstream
  publish grid (every 5 min on the UTC grid, a little after the boundary) so
  data is fresh rather than up to a poll-interval behind.

## Installation (HACS)

This integration relies on the SHMÚ website for the current sky condition (the
open-data files contain no cloud information — see
[Why HACS](#why-hacs-and-not-home-assistant-core)), so it is distributed via
HACS rather than Home Assistant core.

1. HACS → Integrations → ⋮ → *Custom repositories* → add this repository as an
   *Integration*.
2. Install **SHMÚ Weather**, then restart Home Assistant.
3. *Settings → Devices & Services → Add Integration → SHMÚ Weather*. The
   station nearest your Home Assistant location is preselected; pick any of
   the 27 synoptic stations. Add the integration again for more stations.

## How the weather condition is determined

SHMÚ's open-data feed gives accurate measurements but **no cloud cover** and
only sparse present-weather codes, so it cannot produce a reliable sky
condition on its own. The integration therefore takes the condition from the
SHMÚ public current-weather page (cloud + present weather), falling back to
the open-data `stav_poc` code, and reports *unknown* rather than guessing when
neither is available. All numeric values come only from the open data.

### Why HACS and not Home Assistant core

Two reasons, both deliberate for v1:

1. Reading the condition from a web page is "scraping", which Home Assistant
   core discourages.
2. The SHMÚ client is **vendored** into the integration rather than published
   to PyPI; core requires the communication layer to be a separate, published
   package in `manifest.json` requirements.

Both are intentional trade-offs for a self-contained HACS release. The
scraping is isolated to one swappable module and the vendored library is kept
Home-Assistant-free, so a future core-eligible path (Phase-2 ALADIN condition
+ extracting/publishing the library) stays open.

## Roadmap

| Phase | Scope |
|------|-------|
| 1 | Current conditions + CAP warnings (pure Python + website condition) |
| 2 | ALADIN/SHMÚ forecast (GRIB2 — needs a decode-strategy spike) |
| 3 | Quality-scale polish, diagnostics, optional radar / air quality |

## Development

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv pytest pytest-asyncio aioresponses ruff \
    mypy pytest-homeassistant-custom-component
.venv/bin/ruff check custom_components/ tests/
.venv/bin/python -m mypy
.venv/bin/python -m pytest tests/      # 50 tests, fully offline
```

The SHMÚ client library is vendored at `custom_components/shmu/shmu_opendata/`
(kept Home-Assistant-free so it stays swappable and could be extracted to its
own package later); the integration glue is the rest of
`custom_components/shmu/`. See [CLAUDE.md](CLAUDE.md) for the non-obvious
data-source constraints.

## Data source & attribution

Weather and climate data © **Slovenský hydrometeorologický ústav (SHMÚ)**,
provided via <https://opendata.shmu.sk/> under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This project is not
affiliated with or endorsed by SHMÚ.

## License

Code is MIT licensed (see [LICENSE](LICENSE)). SHMÚ data retains its CC BY 4.0
license and must be attributed accordingly.
