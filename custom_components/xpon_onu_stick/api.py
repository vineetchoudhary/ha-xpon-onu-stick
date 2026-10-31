"""Shared polling and session ownership, independent of device page formats."""

import logging

import aiohttp

from .const import DEFAULT_LOGOUT_AFTER_POLL
from .devices.base import DeviceAdapter
from .devices.boa import BoaAdapter
from .devices.boa.auth import _FormResultParser as _FormResultParser
from .devices.boa.parsing import (
    DEVICE_FIELDS,
    GPON_FIELDS,
    OPTICAL_FIELDS,
    PON_FIELDS,
    parse_pon_status_page,
    parse_status_page,
)
from .models import (
    OnuAuthError,
    OnuConnectionError,
    OnuError,
    OnuLoginRequired,
    OnuLogoutError,
    OnuParseError,
    OnuSessionBusy,
    OnuStatus,
    normalize_mac,
)
from .transport import OnuTransport, normalize_host

# Retain the existing client/parser entry points for tools and downstream users.
__all__ = [
    "DEVICE_FIELDS",
    "GPON_FIELDS",
    "OPTICAL_FIELDS",
    "PON_FIELDS",
    "OnuAuthError",
    "OnuClient",
    "OnuConnectionError",
    "OnuError",
    "OnuLogoutError",
    "OnuParseError",
    "OnuSessionBusy",
    "OnuStatus",
    "normalize_host",
    "normalize_mac",
    "parse_pon_status_page",
    "parse_status_page",
]

_LOGGER = logging.getLogger(__name__)


class OnuClient:
    """Read through an adapter while keeping session ownership and polling shared."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str = "",
        password: str = "",
        *,
        logout_after_poll: bool = DEFAULT_LOGOUT_AFTER_POLL,
        adapter: DeviceAdapter | None = None,
    ) -> None:
        # There is one verified interface family today. New families are selected
        # explicitly, never by attempting credentials against several adapters.
        self._adapter = adapter if adapter is not None else BoaAdapter()
        self._transport = OnuTransport(session, host, username, password, self._adapter.policy)
        self.host = self._transport.host
        self._username = username
        self._password = password
        self._logout_after_poll = logout_after_poll
        self._owns_session = False
        self._session_busy = False
        self._field_errors: dict[str, str] = {}
        # Preserve access used by the existing session/serialization regressions.
        self._session = self._transport.session
        self._lock = self._transport.lock
        self._cookie_jar = self._transport.cookie_jar

    def matches_credentials(self, username: str, password: str) -> bool:
        """Allow Home Assistant to reuse this client's login without exposing it."""
        return self._username == username and self._password == password

    async def _request(self, method: str, path: str, data: dict[str, str] | None = None) -> str:
        return await self._transport.request(
            method,
            path,
            data,
            validate_response=lambda status, target: self._adapter.validate_response(
                method, path, status, target
            ),
            is_login_error=self._adapter.is_login_error,
        )

    async def _async_login(self) -> None:
        """Validate one adapter's login form, then verify success by reading status."""
        self._owns_session = False
        self._session_busy = False
        if not self._username:
            raise OnuAuthError("Enter the ONU username and password to sign in")
        payload = self._adapter.login_payload(
            await self._request("GET", self._adapter.login_page_path),
            self.host,
            self._username,
            self._password,
        )
        html = await self._request("POST", self._adapter.login_form_path, payload)
        self._owns_session, self._session_busy = self._adapter.login_result(html)

    async def _async_logout(self) -> None:
        """End only our own session and preserve readings on any logout failure."""
        try:
            html = await self._request(
                "POST", self._adapter.logout_form_path, self._adapter.logout_payload()
            )
        except OnuError as err:
            raise OnuLogoutError("Unable to confirm ONU logout") from err
        self._adapter.validate_logout(html)
        self._transport.cookie_jar.clear()
        self._owns_session = False

    async def _async_read_status(self) -> OnuStatus:
        status = await self._adapter.async_read_status(self._request)
        for key, error in status.field_errors.items():
            if self._field_errors.get(key) != error:
                _LOGGER.error(
                    "%s at %s. This reading is unknown. Other readings will continue updating",
                    error,
                    self.host,
                )
        for key in self._field_errors.keys() - status.field_errors.keys():
            _LOGGER.info("Parsing error cleared for %s at %s", key, self.host)
        self._field_errors = status.field_errors.copy()
        return status

    async def async_get_status(self, *, logout_after_poll: bool | None = None) -> OnuStatus:
        """Serialize access to this address and only log out a login we established."""
        logout = self._logout_after_poll if logout_after_poll is None else logout_after_poll
        async with self._lock:
            try:
                status = await self._async_read_status()
            except OnuLoginRequired:
                self._owns_session = False
                await self._async_login()
                try:
                    status = await self._async_read_status()
                except OnuLoginRequired as err:
                    self._owns_session = False
                    if self._session_busy:
                        raise OnuSessionBusy(
                            "The ONU already has an active management session. "
                            "Sign out of that session before trying again"
                        ) from err
                    raise OnuAuthError(
                        "Login was rejected. Check the username and password"
                    ) from err
                except OnuAuthError:
                    self._owns_session = False
                    raise
            except OnuAuthError:
                self._owns_session = False
                raise
            if logout and self._owns_session:
                try:
                    await self._async_logout()
                except OnuLogoutError:
                    _LOGGER.warning(
                        "Unable to confirm ONU logout after reading status; keeping readings"
                    )
            return status
