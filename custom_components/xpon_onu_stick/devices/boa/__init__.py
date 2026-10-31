"""Adapter for the supported Boa web interface, with shared GPON and EPON parsing."""

from ...const import (
    DEVICE_STATUS_PATH,
    LOGIN_FORM_PATH,
    LOGIN_PAGE_PATH,
    LOGOUT_FORM_PATH,
    LOGOUT_PAGE_PATH,
    PON_STATUS_PATH,
)
from ...models import (
    HttpPolicy,
    OnuAuthError,
    OnuCapabilities,
    OnuLoginRequired,
    OnuLogoutError,
    OnuParseError,
    OnuStatus,
    normalize_mac,
)
from ..base import OnuRequest
from .auth import login_payload, login_result, logout_payload, validate_logout
from .parsing import DEVICE_FIELDS, parse_pon_status_page, parse_status_page
from .profiles import select_profile


class BoaAdapter:
    """Translate captured status/authentication pages into the common client contract."""

    policy = HttpPolicy(
        allowed_requests=frozenset(
            {
                ("GET", DEVICE_STATUS_PATH),
                ("GET", PON_STATUS_PATH),
                ("GET", LOGIN_PAGE_PATH),
                ("POST", LOGIN_FORM_PATH),
                ("POST", LOGOUT_FORM_PATH),
            }
        ),
        post_referers=(
            (LOGIN_FORM_PATH, LOGIN_PAGE_PATH),
            (LOGOUT_FORM_PATH, LOGOUT_PAGE_PATH),
        ),
    )
    login_page_path = LOGIN_PAGE_PATH
    login_form_path = LOGIN_FORM_PATH
    logout_form_path = LOGOUT_FORM_PATH
    login_payload = staticmethod(login_payload)
    login_result = staticmethod(login_result)
    logout_payload = staticmethod(logout_payload)
    validate_logout = staticmethod(validate_logout)

    async def async_read_status(self, request: OnuRequest) -> OnuStatus:
        """Read sequentially and reject an unrelated first page before reading PON."""
        errors: dict[str, str] = {}
        device = parse_status_page(
            await request("GET", DEVICE_STATUS_PATH), DEVICE_FIELDS, field_errors=errors
        )
        mode, pon = parse_pon_status_page(
            await request("GET", PON_STATUS_PATH), field_errors=errors
        )
        profile = select_profile(device["firmware_version"], mode)
        values = {**device, **pon}
        for key in profile.optional_fields:
            if errors.get(key, "").startswith("Status page is missing field: "):
                errors.pop(key)
        for key in profile.unsupported_fields:
            errors.pop(key, None)
            if key in values:
                values[key] = None
        mac = device["mac_address"]
        if not isinstance(mac, str):
            raise OnuParseError("Device identity is missing")
        fields = frozenset(values) - profile.unsupported_fields
        return OnuStatus(
            values=values,
            mac_address=normalize_mac(mac),
            pon_mode=mode,
            field_errors=errors,
            profile_id=profile.id,
            capabilities=OnuCapabilities(
                fields=fields, optional_fields=profile.optional_fields & fields
            ),
        )

    @staticmethod
    def validate_response(method: str, path: str, status: int, redirect_path: str | None) -> None:
        """Recognize authentication redirects without ever following them."""
        if not 300 <= status < 400:
            return
        if path == LOGOUT_FORM_PATH:
            raise OnuLogoutError("The device did not return the logout confirmation")
        if method == "GET" and redirect_path == LOGIN_PAGE_PATH:
            raise OnuLoginRequired("The status endpoint requested login")
        if method != "POST" or redirect_path not in {
            "/",
            LOGIN_PAGE_PATH,
            DEVICE_STATUS_PATH,
            "/admin/status.asp",
        }:
            raise OnuAuthError("The device returned an unsupported redirect")

    @staticmethod
    def is_login_error(status: int, message: str) -> bool:
        """Recognize only the observed headerless login response from this interface."""
        return status == 400 and "Expected HTTP/" in message and LOGIN_PAGE_PATH in message
