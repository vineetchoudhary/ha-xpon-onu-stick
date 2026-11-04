"""Coordinate polling for all ONU sensors."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OnuAuthError, OnuClient, OnuError, OnuStatus
from .const import (
    CONF_LOGOUT_AFTER_POLL,
    DEFAULT_LOGOUT_AFTER_POLL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .devices.odi_oss.ssh import OdiSshClient

_LOGGER = logging.getLogger(__name__)


class OnuCoordinator(DataUpdateCoordinator[OnuStatus]):
    """Share fresh device/PON readings and per-field errors with every sensor."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: OnuClient | OdiSshClient
    ) -> None:
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

    @property
    def device_info(self) -> DeviceInfo:
        """Associate all readings with the existing MAC-based device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.unique_id)},
            connections={(CONNECTION_NETWORK_MAC, self.data.mac_address)},
            name=self.data.values.get("device_name") or self.entry.title,
            model=self.data.values.get("device_name"),
            sw_version=self.data.values.get("firmware_version"),
            configuration_url=self.client.host if isinstance(self.client, OnuClient) else None,
        )

    async def _async_update_data(self) -> OnuStatus:
        try:
            if isinstance(self.client, OdiSshClient):
                status = await self.client.async_get_status()
            else:
                status = await self.client.async_get_status(
                    logout_after_poll=self.entry.options.get(
                        CONF_LOGOUT_AFTER_POLL, DEFAULT_LOGOUT_AFTER_POLL
                    )
                )
            if self.entry.unique_id != status.mac_address:
                raise UpdateFailed("The address now belongs to a different ONU stick")
            return status
        except OnuAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except OnuError as err:
            raise UpdateFailed(str(err)) from err
