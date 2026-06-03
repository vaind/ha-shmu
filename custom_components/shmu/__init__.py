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
    Platform.IMAGE,
    Platform.NUMBER,
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

    # Poll on the upstream UTC 5-minute grid with an auto-tuned offset rather
    # than a fixed period, so each snapshot is fetched just after SHMÚ
    # publishes it. The coordinator owns the (re)scheduling.
    coordinator.async_schedule_refresh()
    entry.async_on_unload(coordinator.async_cancel_refresh)

    # The measurement location resolves once at coordinator construction, and
    # the forecast/radar caches key on the upstream file path (not lat/lon), so
    # editing the location in the options flow must rebuild the coordinator to
    # take effect. Reloading does exactly that (fresh coordinator, empty cache).
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload_on_update(hass: HomeAssistant, entry: ShmuConfigEntry) -> None:
    """Reload the entry when its options change (new measurement location)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ShmuConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
