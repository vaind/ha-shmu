# Contributing

Thanks for helping improve **SHMÚ Weather**. This is an early-stage,
unofficial project (see the disclaimer in [README.md](README.md)).

## Setup

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv pytest pytest-asyncio aioresponses ruff \
    mypy pytest-homeassistant-custom-component
```

## Before you push

```bash
.venv/bin/ruff check custom_components/ tests/
.venv/bin/ruff format custom_components/ tests/
.venv/bin/python -m mypy
.venv/bin/python -m pytest tests/      # must stay green and offline
```

## Ground rules

- **Two layers, one boundary.** The SHMÚ client is vendored at
  `custom_components/shmu/shmu_opendata/` and must **not** import Home
  Assistant (it stays swappable / extractable). The HA glue is the rest of
  `custom_components/shmu/`.
- **Tests are deterministic and offline.** HTTP is mocked (`aioresponses`); HA
  tests use fixture-derived snapshots. Don't add tests that hit the network.
  Add or update a fixture under `tests/fixtures/` instead.
- **Never disable TLS verification** to "fix" an opendata.shmu.sk handshake.
  The server omits an intermediate; refresh the bundled cert instead (see
  [CLAUDE.md](CLAUDE.md)).
- **The scraper (`website.py`) is the only HTML-coupled module** and is meant
  to be swappable. Keep scraping isolated there.
- Reproduce bugs with a test first; fix root causes, not symptoms.
- Match the surrounding style; comment the *why*. Keep PRs small and focused,
  describing the problem and the approach.
- Don't reformat unrelated code.

## Data & attribution

SHMÚ data is CC BY 4.0 and must be attributed. This project is not affiliated
with SHMÚ — don't imply endorsement in code, docs or naming.

See [CLAUDE.md](CLAUDE.md) for the non-obvious data-source constraints learned
by reverse-engineering the source; read it before touching fetch or condition
logic.
