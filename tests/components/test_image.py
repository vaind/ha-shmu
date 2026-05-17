"""Radar image entity tests (rendered via the stubbed client)."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch

import pytest
from homeassistant.components.image import async_get_image
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import CONF_IND_KLI, DOMAIN

from .test_init import _FakeClient

_ENTITY = "image.hurbanovo_radar"


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="11858",
        title="Hurbanovo",
        data={CONF_IND_KLI: 11858},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_radar_image_entity_created(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    state = hass.states.get(_ENTITY)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    attrs = state.attributes
    assert attrs["product"] == "zmax"
    assert attrs["max_dbz"] is not None
    # ODIM corner box over Slovakia/Central Europe.
    assert 45.0 < attrs["bbox_south"] < 47.0
    assert 23.0 < attrs["bbox_east"] < 24.0


async def test_radar_image_serves_png(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    image = await async_get_image(hass, _ENTITY)
    assert image.content_type == "image/png"
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_radar_in_diagnostics(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    from custom_components.shmu.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    diag = await async_get_config_entry_diagnostics(hass, setup_entry)
    radar = diag["radar"]
    assert radar is not None
    assert radar["product"] == "zmax"
    assert radar["size"] == [64, 48]
    assert len(radar["bbox"]) == 4
    assert "png" not in radar  # never dump the image bytes
