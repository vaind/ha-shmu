"""Translation-consistency audit.

`strings.json` is the source of truth. `translations/en.json` must mirror it
verbatim, `translations/sk.json` must have exactly the same key structure (no
missing or extra strings), and every entity ``translation_key`` actually
registered by the integration must resolve to a name in `strings.json`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import CONF_IND_KLI, DOMAIN

from .test_init import _FakeClient

_COMPONENT = Path(__file__).parents[2] / "custom_components" / "shmu"


def _load(name: str) -> dict[str, Any]:
    return json.loads((_COMPONENT / name).read_text(encoding="utf-8"))


def _key_skeleton(value: Any) -> Any:
    """Nested set of keys, ignoring leaf string values (the translations)."""
    if isinstance(value, dict):
        return {k: _key_skeleton(v) for k, v in sorted(value.items())}
    return None


def test_en_mirrors_strings_verbatim() -> None:
    assert _load("strings.json") == _load("translations/en.json")


def test_sk_has_same_key_structure_as_en() -> None:
    en = _load("translations/en.json")
    sk = _load("translations/sk.json")
    assert _key_skeleton(sk) == _key_skeleton(en)


def test_warning_level_enum_states_all_translated() -> None:
    states = _load("strings.json")["entity"]["sensor"]["warning_level"]["state"]
    # Mirrors ShmuWarningLevelSensor._attr_options; HA's Entity metaclass hides
    # that literal behind a descriptor, so assert the known set explicitly.
    assert set(states) == {"none", "green", "yellow", "orange", "red"}


async def test_registered_translation_keys_resolve(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="11858", title="Hurbanovo", data={CONF_IND_KLI: 11858}
    )
    entry.add_to_hass(hass)
    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    strings = _load("strings.json")["entity"]
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert entities  # the integration must register entities at all

    checked = 0
    for entity in entities:
        if entity.translation_key is None:
            continue  # e.g. the weather entity uses the device name
        platform = entity.entity_id.split(".", 1)[0]
        assert entity.translation_key in strings.get(platform, {}), (
            f"{entity.entity_id} translation_key "
            f"{entity.translation_key!r} missing from strings.json"
        )
        checked += 1
    assert checked  # at least the named sensors/binary_sensor were verified
