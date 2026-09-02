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
_FRAME_ENTITY = "image.hurbanovo_radar_frame"
_MAP_ENTITY = "image.hurbanovo_radar_map"
_MAP_LOOP_ENTITY = "image.hurbanovo_radar_map_loop"
_MAP_FRAME_ENTITY = "image.hurbanovo_radar_map_frame"

#: WGS84 corners of the (trimmed) ODIM fixture grid — what a map overlay must
#: report, since it renders the composite whole.
_GRID_SOUTH, _GRID_NORTH = 46.047, 50.7
_GRID_WEST, _GRID_EAST = 13.6, 23.804


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


async def test_radar_frame_image_defaults_to_live(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    state = hass.states.get(_FRAME_ENTITY)
    assert state is not None
    attrs = state.attributes
    # Offset 0 == newest frame (matches the still / stays roll-stable).
    assert attrs["frame_offset"] == 0
    assert attrs["frame_count"] == 3
    assert attrs["valid_at"] == "2026-05-17T20:20:00+00:00"

    image = await async_get_image(hass, _FRAME_ENTITY)
    assert image.content_type == "image/png"
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_radar_map_entity_covers_the_whole_grid(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """The map overlay is the national composite, not the station crop: its
    box is what a Leaflet imageOverlay is stretched between."""
    state = hass.states.get(_MAP_ENTITY)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    attrs = state.attributes
    assert attrs["product"] == "zmax"
    assert attrs["bbox_south"] == pytest.approx(_GRID_SOUTH, abs=0.01)
    assert attrs["bbox_north"] == pytest.approx(_GRID_NORTH, abs=0.01)
    assert attrs["bbox_west"] == pytest.approx(_GRID_WEST, abs=0.01)
    assert attrs["bbox_east"] == pytest.approx(_GRID_EAST, abs=0.01)
    # Still centred on the station, so a map card can focus there.
    assert attrs["center_latitude"] == 47.8733
    assert attrs["center_longitude"] == 18.1944
    # The bundled map plugin positions the picture from the box above and
    # fetches it from `entity_picture`; both are part of the contract it needs.
    assert attrs["entity_picture"].startswith(f"/api/image_proxy/{_MAP_ENTITY}")

    # Strictly wider than the picture-card crop of the same frame.
    cropped = hass.states.get(_ENTITY).attributes
    assert attrs["bbox_north"] - attrs["bbox_south"] > (
        cropped["bbox_north"] - cropped["bbox_south"]
    )

    image = await async_get_image(hass, _MAP_ENTITY)
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert image.content != (await async_get_image(hass, _ENTITY)).content


async def test_radar_map_loop_serves_apng_over_the_same_extent(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    attrs = hass.states.get(_MAP_LOOP_ENTITY).attributes
    assert attrs["frame_count"] == 3
    assert attrs["loop_start"] == "2026-05-17T20:10:00+00:00"
    # The loop and the still must register identically, or the picture jumps
    # on the map when a dashboard swaps one for the other.
    still = hass.states.get(_MAP_ENTITY).attributes
    for key in ("bbox_south", "bbox_west", "bbox_north", "bbox_east"):
        assert attrs[key] == still[key]

    image = await async_get_image(hass, _MAP_LOOP_ENTITY)
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"acTL" in image.content  # animated


async def test_radar_map_frame_follows_the_shared_scrubber(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """One slider drives both the picture card and the map overlay."""
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.hurbanovo_radar_frame_selector", "value": -2},
        blocking=True,
    )
    attrs = hass.states.get(_MAP_FRAME_ENTITY).attributes
    assert attrs["frame_offset"] == 2
    assert attrs["valid_at"] == "2026-05-17T20:10:00+00:00"
    assert attrs["bbox_north"] == pytest.approx(_GRID_NORTH, abs=0.01)

    image = await async_get_image(hass, _MAP_FRAME_ENTITY)
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
    assert radar["loop_frames"] == 3
    assert radar["loop_start"] == "2026-05-17T20:10:00+00:00"
    assert radar["loop_end"] == "2026-05-17T20:20:00+00:00"
    assert radar["selected_offset"] == 0
    w, h = radar["size"]
    assert 0 < w < 64 and 0 < h < 48  # cropped to the station vicinity
    # The map overlay is the whole (fixture) grid, undownsampled.
    assert radar["map_size"] == [64, 48]
    station_png, map_png = radar["png_bytes"]
    assert station_png > 0 and map_png > 0
    # Coarsened to ~0.1° in diagnostics so a private measurement location can
    # never be pinpointed (full precision stays on the live image entity).
    assert radar["center"] == [47.9, 18.2]
    assert len(radar["bbox"]) == 4
    assert "png" not in radar  # never dump the image bytes
    assert "loop_png" not in radar  # nor the animation bytes
