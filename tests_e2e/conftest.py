"""Live-test setup: load the client library on its own, without Home Assistant.

The live tests exercise only the vendored client. Importing it as
``custom_components.shmu.shmu_opendata`` would first run the integration's
``__init__.py`` and load Home Assistant with it, so its parent directory goes
on ``sys.path`` and the tests import it as the top-level ``shmu_opendata`` —
the same way mypy analyses it.

This module also refuses to run with the Home Assistant socket guard loaded.
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
