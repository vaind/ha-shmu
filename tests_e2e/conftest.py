"""Live-test setup.

The client library is imported standalone, as ``shmu_opendata`` (like mypy
does): importing it via ``custom_components.shmu`` would load Home Assistant.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "shmu"))


def pytest_configure(config: pytest.Config) -> None:
    # pytest-homeassistant-custom-component registers itself as an entry-point
    # plugin and blocks every non-localhost socket in every test, so without
    # this check each live test fails with an opaque SocketBlockedError.
    if config.pluginmanager.has_plugin("homeassistant"):
        raise pytest.UsageError(
            "tests_e2e/ needs the network; run it as "
            "`python -m pytest tests_e2e/ -p no:homeassistant`"
        )
