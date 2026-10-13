# Contributing

Thanks for helping improve **SHMÚ Weather**. This is an unofficial community project (see the disclaimer in [README.md](README.md)).

## Setup

```bash
uv venv --python 3.13 .venv
uv pip install --group dev
```

The dev tools are listed once, in the `dev` dependency group in `pyproject.toml`, which CI installs the same way.
Add a new tool there rather than to a command line.
They are loose lower bounds with no lockfile, so Dependabot does not track them (it only bumps the GitHub Actions pins).

## Before you push

```bash
.venv/bin/ruff check custom_components/ tests/ tests_e2e/
.venv/bin/ruff format custom_components/ tests/ tests_e2e/
.venv/bin/python -m mypy
.venv/bin/python -m pytest tests/      # must stay green and offline
```

`tests_e2e/` is the one deliberate exception to "offline": it runs the real client against SHMÚ and checks the upstream facts recorded in [AGENTS.md](AGENTS.md) (freshness, coverage, forecast horizon, radar loop).
The `E2E (live SHMÚ)` workflow (`.github/workflows/e2e.yml`) runs it daily.
Run it yourself after touching a fetch path or when SHMÚ seems to have changed something:

```bash
.venv/bin/python -m pytest tests_e2e/ -p no:homeassistant
```

When it fails, re-verify against the live server before changing code, then record what you found in AGENTS.md.

## Ground rules

- **Two layers, one boundary.** The SHMÚ client is vendored at `custom_components/shmu/shmu_opendata/` and must **not** import Home Assistant (it stays swappable / extractable). The HA glue is the rest of `custom_components/shmu/`.
- **Tests are deterministic and offline.** HTTP is mocked (HA's `AiohttpClientMocker`); HA tests use fixture-derived snapshots. Don't add tests that hit the network outside `tests_e2e/`.
  Add or update a fixture under `tests/fixtures/` instead.
- **Never disable TLS verification** to "fix" an opendata.shmu.sk handshake.
  The server omits an intermediate; refresh the bundled cert instead (see [AGENTS.md](AGENTS.md)).
- **The scraper (`website.py`) is the only HTML-coupled module** and is meant to be swappable. Keep scraping isolated there.
- Reproduce bugs with a test first; fix root causes, not symptoms.
- Match the surrounding style; comment the *why*. Keep PRs small and focused, describing the problem and the approach.
- Don't reformat unrelated code.
- **Don't hard-wrap Markdown prose.** Write one sentence (or list item) per line and let lines run long.
  Line-length limits apply to *code* only (enforced by `ruff`, configured in `pyproject.toml`).
  GitHub renders single newlines in release notes, issue and PR bodies as hard line breaks, and `release.yml` feeds the `CHANGELOG.md` section verbatim into the GitHub Release, so a column-wrapped entry shows ragged mid-sentence breaks in the published notes.

## Why HACS and not Home Assistant core

Two reasons, both deliberate:

1. Reading the condition from a web page is "scraping", which Home Assistant core discourages.
2. The SHMÚ client is **vendored** into the integration rather than published to PyPI; core requires the communication layer to be a separate, published package in `manifest.json` requirements.

Both are intentional trade-offs for a self-contained HACS release. The scraping is isolated to one swappable module and the vendored library is kept Home-Assistant-free, so a future core-eligible path (resolving the condition from open data alone, and extracting and publishing the library) stays open.

## Releasing

A release is a version bump PR followed by a tag; `.github/workflows/release.yml` does the rest.

1. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [x.y.z] - YYYY-MM-DD` and add the `[x.y.z]: …/releases/tag/vx.y.z` link at the bottom.
2. Set the same `version` in `custom_components/shmu/manifest.json`.
3. Merge, then tag the merge commit `vx.y.z` and push the tag.

The workflow refuses a tag that disagrees with the manifest version (HACS resolves releases by tag) or that has no matching changelog section, and publishes that section verbatim as the release notes.
A released section is final: the first change after a release opens a new `## [Unreleased]` above it, rather than adding to the version that has already shipped.

## Data & attribution

SHMÚ data is CC BY 4.0 and must be attributed. This project is not affiliated with SHMÚ — don't imply endorsement in code, docs or naming.

See [AGENTS.md](AGENTS.md) for the non-obvious data-source constraints learned by reverse-engineering the source; read it before touching fetch or condition logic.
