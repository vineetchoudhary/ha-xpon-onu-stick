"""Home Assistant integration for XPON ONU Stick."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OnuClient
from .coordinator import OnuCoordinator

PLATFORMS = [Platform.SENSOR]
type OnuConfigEntry = ConfigEntry[OnuCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: OnuConfigEntry) -> bool:
    """Validate both pages before adding sensors."""
    client = OnuClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data.get(CONF_USERNAME, ""),
        entry.data.get(CONF_PASSWORD, ""),
    )
    coordinator = OnuCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OnuConfigEntry) -> bool:
    """Unload entities and their polling listeners."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
