"""Retain the integration's own login across validation, polling, and reloads."""

from collections.abc import Mapping
from typing import Any

import aiohttp
from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import OnuClient, normalize_host
from .const import CONF_SSH_FINGERPRINT, CONF_SSH_KEY_FILE, DOMAIN
from .devices.odi_oss.ssh import OdiSshClient

_DATA_CLIENTS = f"{DOMAIN}_clients"
_DATA_HTTP = f"{DOMAIN}_http"


@callback
def _async_get_transport(hass: HomeAssistant) -> aiohttp.ClientSession:
    """Keep automatic cookies out of the transport and other integrations."""
    if _DATA_HTTP not in hass.data:
        transport = async_create_clientsession(
            hass, cookie_jar=aiohttp.DummyCookieJar(), auto_cleanup=False
        )
        # The transport outlives entry reloads. HA owns its shared connector.
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, callback(lambda _: transport.detach()))
        hass.data[_DATA_HTTP] = transport
    return hass.data[_DATA_HTTP]


@callback
def async_get_onu_client(
    hass: HomeAssistant, host: str, username: str = "", password: str = ""
) -> OnuClient:
    """Keep one current client per configured address, without credentials as keys."""
    host = normalize_host(host)
    clients = hass.data.setdefault(_DATA_CLIENTS, {})
    client = clients.get(host)
    if client is None or not client.matches_credentials(username, password):
        client = OnuClient(_async_get_transport(hass), host, username, password)
    return client


@callback
def async_remember_onu_client(hass: HomeAssistant, client: OnuClient) -> None:
    """Cache only validated clients, so a failed login cannot replace a working one."""
    hass.data.setdefault(_DATA_CLIENTS, {})[client.host] = client


@callback
def async_forget_onu_client(hass: HomeAssistant, host: str) -> None:
    """Release cached credentials and cookies when the configured device is removed."""
    clients = hass.data.get(_DATA_CLIENTS, {})
    clients.pop(normalize_host(host), None)


@callback
def async_create_ssh_client(hass: HomeAssistant, data: Mapping[str, Any]) -> OdiSshClient:
    """Create a client owned by one validation or loaded entry."""
    return OdiSshClient(
        data[CONF_HOST],
        data[CONF_PORT],
        hass.config.path(),
        data[CONF_SSH_KEY_FILE],
        data[CONF_SSH_FINGERPRINT],
    )
