"""Live-test setup: refuse to run with the Home Assistant socket guard loaded."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    # pytest-homeassistant-custom-component registers itself as an entry-point
    # plugin and blocks every non-localhost socket in every test, so without
    # this check each live test fails with an opaque SocketBlockedError.
    if config.pluginmanager.has_plugin("homeassistant"):
        raise pytest.UsageError(
            "tests_e2e/ needs the network; run it as "
            "`python -m pytest tests_e2e/ -p no:homeassistant`"
        )
