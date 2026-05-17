# AGENTS.md

Guidance for AI coding agents working in this repo. Keep it concise; the
detailed, non-obvious data-source notes live in [CLAUDE.md](CLAUDE.md) — read
that before changing fetch or condition logic.

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
   them, and document what you verified (see the CAP-issuance note in
   CLAUDE.md). Don't add speculative workarounds for failure modes that don't
   occur.

## Layout

| Path | What |
|---|---|
| `custom_components/shmu/shmu_opendata/` | Vendored client library (no HA deps) |
| `custom_components/shmu/` | Home Assistant integration (the glue) |
| `tests/` | Fast offline library tests |
| `tests/components/` | HA integration tests (`pytest-homeassistant-custom-component`) |

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and workflow,
[CLAUDE.md](CLAUDE.md) for data-source constraints and the roadmap.
