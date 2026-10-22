"""Status client with HTTP Basic and Realtek/Boa form authentication."""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

import aiohttp
from yarl import URL

from .const import (
    DEFAULT_LOGOUT_AFTER_POLL,
    DEVICE_STATUS_PATH,
    LOGIN_FORM_PATH,
    LOGIN_PAGE_PATH,
    LOGOUT_FORM_PATH,
    LOGOUT_PAGE_PATH,
    PON_STATUS_PATH,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class OnuError(Exception):
    """Base error from the ONU client."""


class OnuConnectionError(OnuError):
    """The status interface could not be reached."""


class OnuAuthError(OnuError):
    """The status interface requires authentication."""


class _OnuLoginRequired(OnuAuthError):
    """The firmware requested a new browser login session."""


class OnuParseError(OnuError):
    """A response is not a supported status page."""


class OnuLogoutError(OnuError):
    """The ONU did not confirm that its management session was closed."""


def normalize_host(host: str) -> str:
    """Accept a hostname/IP or base URL without credentials or an action path."""
    host = host.strip()
    if not host or any(char.isspace() for char in host):
        raise ValueError("Enter a hostname, IP address, or HTTP(S) base URL")
    if "://" not in host:
        host = f"http://{host}"
    try:
        url = URL(host)
        valid = (
            url.scheme in {"http", "https"}
            and url.host
            and url.user is None
            and url.password is None
            and url.path in {"", "/"}
            and not url.query_string
            and not url.fragment
            and url.port is not None
        )
    except ValueError as err:
        raise ValueError("Invalid device address") from err
    if not valid:
        raise ValueError("Use only the device's base URL, without credentials or a path")
    return str(url.origin())


def normalize_mac(value: str) -> str:
    """Create a stable identity from the device's MAC address."""
    compact = re.sub(r"[:.\-]", "", value).lower()
    if not re.fullmatch(r"[0-9a-f]{12}", compact):
        raise OnuParseError("Invalid MAC address on Device Status page")
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


class _StatusTableParser(HTMLParser):
    """Read table rows, tolerating this firmware's unclosed font/b tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: dict[str, str] = {}
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._cells: list[str] = []
        self._text: list[str] | None = None
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored += 1
        if self._ignored:
            return
        if tag == "table":
            self._finish_row()
            self._table = []
            self.tables.append(self._table)
        elif tag == "tr":
            self._finish_row()
            self._cells = []
        elif tag in {"td", "th"}:
            self._finish_cell()
            self._text = []
        elif tag == "br" and self._text is not None:
            self._text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._ignored = max(0, self._ignored - 1)
        if self._ignored:
            return
        if tag in {"td", "th"}:
            self._finish_cell()
        elif tag in {"tr", "table"}:
            self._finish_row()
            self._cells = []
            if tag == "table":
                self._table = None

    def handle_data(self, data: str) -> None:
        if self._text is not None and not self._ignored:
            self._text.append(data)

    def _finish_cell(self) -> None:
        if self._text is not None:
            self._cells.append(" ".join("".join(self._text).split()))
            self._text = None

    def _finish_row(self) -> None:
        self._finish_cell()
        if self._cells and self._table is not None:
            self._table.append(self._cells)
        if len(self._cells) == 2:
            self.rows[self._cells[0].rstrip(":").strip().casefold()] = self._cells[1]
        self._cells = []


DEVICE_FIELDS = {
    "device name": "device_name",
    "uptime": "uptime",
    "firmware version": "firmware_version",
    "cpu usage": "cpu_usage",
    "memory usage": "memory_usage",
    "ip address": "ip_address",
    "subnet mask": "subnet_mask",
    "mac address": "mac_address",
}
PON_FIELDS = {
    "temperature": "temperature",
    "voltage": "voltage",
    "tx power": "tx_power",
    "rx power": "rx_power",
    "bias current": "bias_current",
    "onu state": "onu_state",
    "onu id": "onu_id",
    "loid status": "loid_status",
}
GPON_FIELDS = {label: PON_FIELDS[label] for label in ("onu state", "onu id", "loid status")}
OPTICAL_FIELDS = {label: key for label, key in PON_FIELDS.items() if label not in GPON_FIELDS}
_NUMBER_UNITS = {
    "cpu_usage": "%",
    "memory_usage": "%",
    "temperature": "(?:°?C)",
    "voltage": "V",
    "tx_power": "dBm",
    "rx_power": "dBm",
    "bias_current": "mA",
    "onu_id": "",
}
_UNKNOWN_VALUES = {"", "-", "--", "n/a", "na", "unknown", "not available"}


def _parse_value(raw: str, label: str, key: str) -> str | float | int | None:
    """Validate one reading without substituting a fabricated number."""
    if raw.casefold() in _UNKNOWN_VALUES:
        return None
    if key not in _NUMBER_UNITS:
        return raw
    match = re.fullmatch(
        rf"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:{_NUMBER_UNITS[key]})?",
        raw,
        re.IGNORECASE,
    )
    if not match:
        raise OnuParseError(f"Invalid number for {label}: {raw!r}")
    number = float(match[1])
    if not math.isfinite(number):
        raise OnuParseError(f"Non-finite number for {label}: {raw!r}")
    if key == "onu_id":
        if number < 0 or not number.is_integer():
            raise OnuParseError(f"Invalid ONU ID: {raw!r}")
        return int(number)
    return number


def _parse_status_table(html: str) -> _StatusTableParser:
    """Read table content, rejecting authentication pages first."""
    if re.search(r"<input\b[^>]*\btype\s*=\s*['\"]?password\b", html, re.IGNORECASE):
        raise _OnuLoginRequired("The device returned a login form")
    if re.search(r"href\s*=\s*['\"]?/admin/login\.asp(?:['\"\s>])", html, re.IGNORECASE):
        raise _OnuLoginRequired("The device requested login")
    parser = _StatusTableParser()
    parser.feed(html)
    parser.close()
    parser._finish_row()
    return parser


def _extract_fields(
    parser: _StatusTableParser,
    fields: dict[str, str],
    *,
    field_errors: dict[str, str] | None = None,
) -> dict[str, str | float | int | None]:
    """Convert each field independently without discarding other valid readings."""
    values: dict[str, str | float | int | None] = {}
    for label, key in fields.items():
        try:
            if label not in parser.rows:
                raise OnuParseError(f"Status page is missing field: {label}")
            values[key] = _parse_value(parser.rows[label], label, key)
        except OnuParseError as err:
            values[key] = None
            if field_errors is not None:
                field_errors[key] = str(err)
    return values


def parse_status_page(
    html: str, fields: dict[str, str], *, field_errors: dict[str, str] | None = None
) -> dict[str, str | float | int | None]:
    """Extract readings independently. Reject login or unrelated pages as a whole."""
    parser = _parse_status_table(html)
    if not fields.keys() & parser.rows.keys():
        raise OnuParseError("Status page has no supported fields")
    return _extract_fields(parser, fields, field_errors=field_errors)


def parse_pon_status_page(
    html: str, *, field_errors: dict[str, str] | None = None
) -> tuple[str, dict[str, str | float | int | None]]:
    """Recognize the GPON rows or the captured EPON LLID status table."""
    parser = _parse_status_table(html)
    epon_tables = [
        table
        for table in parser.tables
        if table and [cell.casefold() for cell in table[0]] == ["epon llid status"]
    ]
    if not epon_tables:
        # Missing GPON readings are isolated, but never imply EPON mode.
        has_gpon_heading = any(
            [cell.casefold() for cell in row] == ["gpon status"]
            for table in parser.tables
            for row in table
        )
        if not PON_FIELDS.keys() & parser.rows.keys() or not (
            has_gpon_heading or GPON_FIELDS.keys() & parser.rows.keys()
        ):
            raise OnuParseError("Status page has no recognized PON mode")
        return "gpon", _extract_fields(parser, PON_FIELDS, field_errors=field_errors)
    if len(epon_tables) != 1 or GPON_FIELDS.keys() & parser.rows.keys():
        raise OnuParseError("Ambiguous PON status page")
    values = _extract_fields(parser, OPTICAL_FIELDS, field_errors=field_errors)
    table = epon_tables[0]
    if len(table) < 3 or [cell.casefold() for cell in table[1]] != ["index", "status"]:
        raise OnuParseError("Invalid EPON LLID table")
    for row in table[2:]:
        if len(row) != 2 or not re.fullmatch(r"[0-9]+", row[0]):
            raise OnuParseError("Invalid EPON LLID index")
        try:
            index = int(row[0])
        except ValueError as err:
            raise OnuParseError("Invalid EPON LLID index") from err
        key = f"epon_llid_{index}_status"
        if key in values:
            raise OnuParseError("Duplicate EPON LLID index")
        raw = row[1]
        if raw.casefold() in _UNKNOWN_VALUES:
            values[key] = None
        else:
            try:
                if not re.fullmatch(r"[0-9]+", raw):
                    raise ValueError("Expected a nonnegative integer")
                # Preserve firmware codes; they are not GPON O1–O7 states.
                values[key] = int(raw)
            except ValueError:
                values[key] = None
                if field_errors is not None:
                    field_errors[key] = f"Invalid EPON LLID status for index {index}: {raw!r}"
    return "epon", values


@dataclass(frozen=True)
class OnuStatus:
    """One poll of both pages, with invalid readings isolated by field."""

    values: dict[str, str | float | int | None]
    mac_address: str
    pon_mode: str = "gpon"
    field_errors: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """Use a stable display name when EPON firmware omits Device Name."""
        fallback = (
            f"XPON ONU {self.mac_address}"
            if self.pon_mode == "epon"
            else f"XPON ONU Stick ({self.mac_address})"
        )
        return str(self.values.get("device_name") or fallback)


class _LoginFormParser(HTMLParser):
    """Extract only the verified login form, ignoring language/settings forms."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden: dict[str, str] = {}
        self.fields: set[str] = set()
        self.valid = False
        self._in_login_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self._in_login_form = (
                attributes.get("action") == LOGIN_FORM_PATH
                and (attributes.get("method") or "get").lower() == "post"
            )
        elif tag == "input" and self._in_login_form and (name := attributes.get("name")):
            self.fields.add(name)
            if (attributes.get("type") or "text").lower() == "hidden":
                self.hidden[name] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._in_login_form:
            self.valid = {"username", "password", "save"} <= self.fields
            self._in_login_form = False


class _LogoutResultParser(HTMLParser):
    """Recognize the visible success heading captured from the logout response."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.success = False
        self._heading: list[str] | None = None
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored += 1
        if not self._ignored and tag == "h4":
            self._heading = []

    def handle_data(self, data: str) -> None:
        if self._heading is not None and not self._ignored:
            self._heading.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._ignored = max(0, self._ignored - 1)
        if not self._ignored and tag == "h4" and self._heading is not None:
            message = " ".join("".join(self._heading).split()).casefold()
            self.success |= message == "ok: logout successfully!"
            self._heading = None


class OnuClient:
    """Read status pages, optionally logging out after successful reads."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str = "",
        password: str = "",
        *,
        logout_after_poll: bool = DEFAULT_LOGOUT_AFTER_POLL,
    ) -> None:
        self._session = session
        self.host = normalize_host(host)
        self._username = username
        self._password = password
        self._logout_after_poll = logout_after_poll
        self._lock = asyncio.Lock()
        self._field_errors: dict[str, str] = {}
        # Home Assistant's shared HTTP session must not own this device's login
        # state. Keep cookies per client, accepting the ONU's numeric IP address.
        self._cookie_jar = aiohttp.CookieJar(unsafe=True)
        try:
            self._headers = (
                {"Authorization": aiohttp.encode_basic_auth(username, password)} if username else {}
            )
        except ValueError as err:
            raise OnuAuthError("Invalid HTTP Basic credentials") from err

    def _redirect_path(self, location: str) -> str | None:
        try:
            target = URL(self.host).join(URL(location))
            if target.origin() == URL(self.host) and not target.user and not target.query_string:
                return target.path
        except ValueError:
            pass
        return None

    async def _request(self, method: str, path: str, data: dict[str, str] | None = None) -> str:
        url = URL(f"{self.host}{path}")
        headers = dict(self._headers)
        kwargs = {}
        if method == "POST":
            referer = LOGOUT_PAGE_PATH if path == LOGOUT_FORM_PATH else LOGIN_PAGE_PATH
            headers["Referer"] = f"{self.host}{referer}"
            kwargs["data"] = data
        request = self._session.get if method == "GET" else self._session.post
        try:
            async with request(
                url,
                headers=headers,
                cookies=self._cookie_jar.filter_cookies(url),
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                allow_redirects=False,
                **kwargs,
            ) as response:
                self._cookie_jar.update_cookies(response.cookies, response_url=url)
                if response.status in {401, 403}:
                    raise OnuAuthError("Authentication is required or credentials are invalid")
                if 300 <= response.status < 400:
                    if path == LOGOUT_FORM_PATH:
                        raise OnuLogoutError("The device did not return the logout confirmation")
                    target = self._redirect_path(response.headers.get("Location", ""))
                    if method == "GET" and target == LOGIN_PAGE_PATH:
                        raise _OnuLoginRequired("The status endpoint requested login")
                    if method != "POST" or target not in {
                        "/",
                        LOGIN_PAGE_PATH,
                        DEVICE_STATUS_PATH,
                        "/admin/status.asp",
                    }:
                        raise OnuAuthError("The device returned an unsupported redirect")
                response.raise_for_status()
                return await response.text(errors="replace")
        except aiohttp.ClientResponseError as err:
            # This firmware returns headerless HTML for an expired session on
            # /status.asp and /status_pon.asp. aiohttp rejects it before providing
            # a response. Only the observed login-page signature means re-login.
            if (
                err.status == 400
                and "Expected HTTP/" in err.message
                and LOGIN_PAGE_PATH in err.message
            ):
                raise _OnuLoginRequired("The status endpoint requested login") from err
            raise OnuConnectionError(f"Unable to read {path}") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise OnuConnectionError(f"Unable to read {path}") from err

    async def _async_login(self) -> None:
        """Reproduce the observed form POST, then let status reads verify success."""
        if not self._username:
            raise OnuAuthError("Enter the ONU username and password to sign in")
        parser = _LoginFormParser()
        parser.feed(await self._request("GET", LOGIN_PAGE_PATH))
        parser.close()
        if not parser.valid or parser.hidden.get("challenge"):
            raise OnuAuthError("The device returned an unsupported login form")
        payload = {
            **parser.hidden,
            "challenge": "",
            "username": self._username,
            "password": self._password,
            "save": "Login",
            "submit-url": LOGIN_PAGE_PATH,
        }
        await self._request("POST", LOGIN_FORM_PATH, payload)

    async def _async_logout(self) -> None:
        """Reproduce the captured logout POST and require the device's acknowledgement."""
        try:
            html = await self._request(
                "POST", LOGOUT_FORM_PATH, {"save": "Logout", "submit-url": LOGOUT_PAGE_PATH}
            )
        except OnuError as err:
            # Logout failure must not trigger a credentials prompt or a new login.
            raise OnuLogoutError("Unable to confirm ONU logout") from err
        parser = _LogoutResultParser()
        parser.feed(html)
        parser.close()
        if not parser.success:
            raise OnuLogoutError("The device did not confirm successful logout")
        self._cookie_jar.clear()

    async def _async_read_status(self) -> OnuStatus:
        """Use sequential requests to keep the embedded server's load low."""
        field_errors: dict[str, str] = {}
        device = parse_status_page(
            await self._request("GET", DEVICE_STATUS_PATH),
            DEVICE_FIELDS,
            field_errors=field_errors,
        )
        mode, pon = parse_pon_status_page(
            await self._request("GET", PON_STATUS_PATH), field_errors=field_errors
        )
        if mode == "epon":
            # This firmware intentionally hides Device Name; use the MAC-based title.
            field_errors.pop("device_name", None)
        mac = device["mac_address"]
        if not isinstance(mac, str):
            raise OnuParseError("Device identity is missing")
        identity = normalize_mac(mac)
        for key, error in field_errors.items():
            if self._field_errors.get(key) != error:
                _LOGGER.error(
                    "%s at %s. This reading is unknown. Other readings will continue updating",
                    error,
                    self.host,
                )
        for key in self._field_errors.keys() - field_errors.keys():
            _LOGGER.info("Parsing error cleared for %s at %s", key, self.host)
        self._field_errors = field_errors.copy()
        return OnuStatus(
            values={**device, **pon},
            mac_address=identity,
            pon_mode=mode,
            field_errors=field_errors,
        )

    async def async_get_status(self) -> OnuStatus:
        """Read a snapshot, then optionally log out before releasing the poll lock."""
        async with self._lock:
            try:
                status = await self._async_read_status()
            except _OnuLoginRequired:
                await self._async_login()
                try:
                    status = await self._async_read_status()
                except _OnuLoginRequired as err:
                    raise OnuAuthError(
                        "Login was rejected. Check the username and password"
                    ) from err
            if self._logout_after_poll:
                try:
                    await self._async_logout()
                except OnuLogoutError:
                    _LOGGER.warning(
                        "Unable to confirm ONU logout after reading status; keeping readings"
                    )
            return status
