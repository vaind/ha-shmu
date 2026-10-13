"""Live check that ``.python-version`` still satisfies the newest Home Assistant.

HA runs on one Python minor at a time (architecture ADR-0020) and moves on
without a fixed schedule. When it does, installing the unpinned
``pytest-homeassistant-custom-component`` does not fail: uv quietly picks the
last release that fits our Python, and the offline suite keeps passing against
an ever older HA. This turns that drift into a failed scheduled run.
"""

from __future__ import annotations

import json
import platform
import urllib.request
from pathlib import Path

from packaging.specifiers import SpecifierSet

PYPI_HOMEASSISTANT = "https://pypi.org/pypi/homeassistant/json"
PYTHON_VERSION_FILE = Path(__file__).parents[1] / ".python-version"


def test_python_version_satisfies_newest_home_assistant() -> None:
    with urllib.request.urlopen(PYPI_HOMEASSISTANT, timeout=30) as response:
        info = json.load(response)["info"]
    ha_version, requires_python = info["version"], info["requires_python"]

    # Check the interpreter, not the file: HA's floor can name a patch
    # (">=3.14.2") and ".python-version" names only the minor.
    running = platform.python_version()
    pinned = PYTHON_VERSION_FILE.read_text().strip()
    assert running == pinned or running.startswith(f"{pinned}."), (
        f"running Python {running}, but .python-version says {pinned}; "
        "run it from the venv `uv venv .venv` creates"
    )
    assert running in SpecifierSet(requires_python), (
        f"Home Assistant {ha_version} requires Python {requires_python}, but "
        f".python-version is {pinned} (running {running}). Bump .python-version "
        "and the ruff target-version / mypy python_version in pyproject.toml, "
        "and raise the minimum in hacs.json to the first HA release requiring "
        "the new Python."
    )
