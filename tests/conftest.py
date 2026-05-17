"""Shared test helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

# Load the Home Assistant test harness (provides `hass`,
# `enable_custom_integrations`, …). Only the tests under tests/components use
# it; the fast library tests are unaffected.
pytest_plugins = ("pytest_homeassistant_custom_component",)

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture() -> Callable[[str], bytes]:
    """Return a loader for files under ``tests/fixtures``."""

    def _load(name: str) -> bytes:
        return (_FIXTURES / name).read_bytes()

    return _load
