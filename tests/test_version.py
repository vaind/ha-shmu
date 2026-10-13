"""The vendored library's version tracks the integration it ships in."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.shmu import shmu_opendata

_MANIFEST = (
    Path(__file__).parent.parent / "custom_components" / "shmu" / "manifest.json"
)


def test_library_version_matches_manifest() -> None:
    # Diagnostics reports both; the library is never released on its own, so
    # two numbers that disagree would only mislead whoever reads a bug report.
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert shmu_opendata.__version__ == manifest["version"]
