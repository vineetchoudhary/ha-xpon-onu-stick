"""Home Assistant integration for XPON ONU Stick."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.setup import async_when_setup

from .client import (
    async_create_ssh_client,
    async_forget_onu_client,
    async_get_onu_client,
    async_remember_onu_client,
)
from .const import CONF_CONNECTION_TYPE, CONNECTION_ODI_SSH, DOMAIN
from .coordinator import OnuCoordinator
from .devices.odi_oss.ssh import OdiSshClient
from .frontend import async_register_card

PLATFORMS = [Platform.SENSOR]
SSH_PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
type OnuConfigEntry = ConfigEntry[OnuCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the card once the frontend and its dashboard resources are ready."""
    async_when_setup(hass, "frontend", async_register_card)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OnuConfigEntry) -> bool:
    """Validate a snapshot before adding entities."""
    if entry.data.get(CONF_CONNECTION_TYPE) == CONNECTION_ODI_SSH:
        client = async_create_ssh_client(hass, entry.data)
    else:
        client = async_get_onu_client(
            hass,
            entry.data[CONF_HOST],
            entry.data.get(CONF_USERNAME, ""),
            entry.data.get(CONF_PASSWORD, ""),
        )
    coordinator = OnuCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        if isinstance(client, OdiSshClient):

            async def async_close_on_stop(_event: Event) -> None:
                await client.async_close()

            entry.async_on_unload(
                hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_close_on_stop)
            )
            await hass.config_entries.async_forward_entry_setups(entry, SSH_PLATFORMS)
        else:
            async_remember_onu_client(hass, client)
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        if isinstance(client, OdiSshClient):
            await client.async_close()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OnuConfigEntry) -> bool:
    """Unload entities and their polling listeners."""
    client = entry.runtime_data.client
    if isinstance(client, OdiSshClient):
        if not await hass.config_entries.async_unload_platforms(entry, SSH_PLATFORMS):
            return False
        await client.async_close()
        return True
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: OnuConfigEntry) -> None:
    """Release the device's retained login when its integration is removed."""
    if entry.data.get(CONF_CONNECTION_TYPE) != CONNECTION_ODI_SSH:
        async_forget_onu_client(hass, entry.data[CONF_HOST])
