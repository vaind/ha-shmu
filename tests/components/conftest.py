"""Fixtures for the Home Assistant integration tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

_FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: object,
) -> None:
    """Load the `shmu` custom integration for every test in this package."""
    return


@pytest.fixture
def load() -> Callable[[str], bytes]:
    """Loader for files under tests/fixtures."""

    def _load(name: str) -> bytes:
        return (_FIXTURES / name).read_bytes()

    return _load
