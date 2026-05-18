"""Radar-frame scrubber (number) tests via the stubbed client."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch

import pytest
from homeassistant.components.image import async_get_image
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import CONF_IND_KLI, DOMAIN

from .test_init import _FakeClient

_NUMBER = "number.hurbanovo_radar_frame_selector"
_FRAME_IMAGE = "image.hurbanovo_radar_frame"


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


async def _set(hass: HomeAssistant, value: float) -> None:
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _NUMBER, "value": value},
        blocking=True,
    )


async def test_scrubber_created_as_slider_spanning_the_buffer(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    state = hass.states.get(_NUMBER)
    assert state is not None
    assert float(state.state) == 0.0  # default == live / newest
    attrs = state.attributes
    assert attrs["mode"] == "slider"
    assert attrs["min"] == 0
    assert attrs["max"] == 2  # 3 buffered frames -> offsets 0..2
    assert attrs["step"] == 1
    assert attrs["frame_count"] == 3
    assert attrs["selected_valid_at"] == "2026-05-17T20:20:00+00:00"


async def test_scrubbing_moves_the_selectable_frame_image(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    await _set(hass, 2)  # oldest buffered frame

    assert float(hass.states.get(_NUMBER).state) == 2.0
    img_state = hass.states.get(_FRAME_IMAGE)
    assert img_state.attributes["frame_offset"] == 2
    assert img_state.attributes["valid_at"] == "2026-05-17T20:10:00+00:00"
    # The image endpoint still serves a valid PNG for the scrubbed frame.
    image = await async_get_image(hass, _FRAME_IMAGE)
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"
