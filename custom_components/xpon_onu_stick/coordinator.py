"""Coordinate polling for all ONU sensors."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OnuAuthError, OnuClient, OnuError, OnuStatus
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class OnuCoordinator(DataUpdateCoordinator[OnuStatus]):
    """A complete device/PON snapshot shared by every sensor."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: OnuClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            always_update=False,
        )
        self.client = client
        self.entry = entry

    async def _async_update_data(self) -> OnuStatus:
        try:
            status = await self.client.async_get_status()
            if self.entry.unique_id != status.mac_address:
                raise UpdateFailed("The address now belongs to a different ONU stick")
            return status
        except OnuAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except OnuError as err:
            raise UpdateFailed(str(err)) from err
