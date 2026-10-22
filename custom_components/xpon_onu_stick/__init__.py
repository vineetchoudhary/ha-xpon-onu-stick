"""Home Assistant integration for XPON ONU Stick."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.setup import async_when_setup

from .client import async_forget_onu_client, async_get_onu_client, async_remember_onu_client
from .const import DOMAIN
from .coordinator import OnuCoordinator
from .frontend import async_register_card

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
type OnuConfigEntry = ConfigEntry[OnuCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the card once the frontend and its dashboard resources are ready."""
    async_when_setup(hass, "frontend", async_register_card)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OnuConfigEntry) -> bool:
    """Validate both pages before adding sensors."""
    client = async_get_onu_client(
        hass,
        entry.data[CONF_HOST],
        entry.data.get(CONF_USERNAME, ""),
        entry.data.get(CONF_PASSWORD, ""),
    )
    coordinator = OnuCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    async_remember_onu_client(hass, client)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OnuConfigEntry) -> bool:
    """Unload entities and their polling listeners."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: OnuConfigEntry) -> None:
    """Release the device's retained login when its integration is removed."""
    async_forget_onu_client(hass, entry.data[CONF_HOST])
