"""The SHMÚ Weather integration.

Weather and climate data © Slovenský hydrometeorologický ústav (SHMÚ),
https://opendata.shmu.sk/, licensed CC BY 4.0.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .coordinator import ShmuConfigEntry, ShmuDataUpdateCoordinator
from .shmu_opendata import ShmuClient, create_ssl_context

PLATFORMS: list[Platform] = [
    Platform.WEATHER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ShmuConfigEntry) -> bool:
    """Set up SHMÚ Weather from a config entry."""
    # SHMÚ omits a TLS intermediate; building the verifying context reads a
    # bundled certificate from disk, so do it off the event loop. The context
    # is applied per request, so HA's shared, auto-managed session can be used
    # (no custom connector / manual lifecycle).
    ssl_context = await hass.async_add_executor_job(create_ssl_context)
    session = async_get_clientsession(hass)

    client = ShmuClient(session, ssl_context=ssl_context)
    coordinator = ShmuDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ShmuConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
