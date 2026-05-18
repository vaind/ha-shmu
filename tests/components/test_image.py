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
_LOOP_ENTITY = "image.hurbanovo_radar_loop"


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
    # Cropped to the configured station (Hurbanovo, 47.87 N / 18.19 E);
    # the crop box must be centred on and contain it.
    assert attrs["center_latitude"] == 47.8733
    assert attrs["center_longitude"] == 18.1944
    assert attrs["bbox_south"] <= 47.8733 <= attrs["bbox_north"]
    assert attrs["bbox_west"] <= 18.1944 <= attrs["bbox_east"]
    # ...and a strict sub-box of the full ODIM domain (~46-50.7 N).
    assert attrs["bbox_south"] > 46.04
    assert attrs["bbox_north"] < 50.7


async def test_radar_image_serves_png(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    image = await async_get_image(hass, _ENTITY)
    assert image.content_type == "image/png"
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_radar_loop_entity_created(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    state = hass.states.get(_LOOP_ENTITY)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    attrs = state.attributes
    assert attrs["product"] == "zmax"
    assert attrs["frame_count"] == 3  # the fake client backfills three frames
    assert attrs["loop_start"] == "2026-05-17T20:10:00+00:00"
    assert attrs["loop_end"] == "2026-05-17T20:20:00+00:00"
    # Same crop/extent as the still image.
    assert attrs["bbox_south"] <= 47.8733 <= attrs["bbox_north"]
    assert attrs["bbox_west"] <= 18.1944 <= attrs["bbox_east"]


async def test_radar_loop_serves_apng(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    image = await async_get_image(hass, _LOOP_ENTITY)
    assert image.content_type == "image/png"
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"
    # APNG: the animation-control chunk makes the same <img> loop.
    assert b"acTL" in image.content


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
    assert radar["loop_frames"] == 3
    assert radar["loop_start"] == "2026-05-17T20:10:00+00:00"
    assert radar["loop_end"] == "2026-05-17T20:20:00+00:00"
    w, h = radar["size"]
    assert 0 < w < 64 and 0 < h < 48  # cropped to the station vicinity
    assert radar["center"] == [47.8733, 18.1944]
    assert len(radar["bbox"]) == 4
    assert "png" not in radar  # never dump the image bytes
    assert "loop_png" not in radar  # nor the animation bytes
