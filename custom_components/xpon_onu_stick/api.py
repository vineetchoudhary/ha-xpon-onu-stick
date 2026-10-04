"""Status client with HTTP Basic and Realtek/Boa form authentication."""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from html.parser import HTMLParser

import aiohttp
from yarl import URL

from .const import (
    DEVICE_STATUS_PATH,
    LOGIN_FORM_PATH,
    LOGIN_PAGE_PATH,
    PON_STATUS_PATH,
    REQUEST_TIMEOUT,
)


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
        self._cells: list[str] = []
        self._text: list[str] | None = None
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored += 1
        if self._ignored:
            return
        if tag == "tr":
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
        elif tag == "tr":
            self._finish_row()
            self._cells = []

    def handle_data(self, data: str) -> None:
        if self._text is not None and not self._ignored:
            self._text.append(data)

    def _finish_cell(self) -> None:
        if self._text is not None:
            self._cells.append(" ".join("".join(self._text).split()))
            self._text = None

    def _finish_row(self) -> None:
        self._finish_cell()
        if len(self._cells) == 2:
            self.rows[self._cells[0].rstrip(":").strip().casefold()] = self._cells[1]


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


def parse_status_page(html: str, fields: dict[str, str]) -> dict[str, str | float | int | None]:
    """Extract the expected page fields. Reject login, error, or unrelated pages."""
    if re.search(r"<input\b[^>]*\btype\s*=\s*['\"]?password\b", html, re.IGNORECASE):
        raise _OnuLoginRequired("The device returned a login form")
    if re.search(r"href\s*=\s*['\"]?/admin/login\.asp(?:['\"\s>])", html, re.IGNORECASE):
        raise _OnuLoginRequired("The device requested login")
    parser = _StatusTableParser()
    parser.feed(html)
    parser.close()
    parser._finish_row()
    missing = fields.keys() - parser.rows.keys()
    if missing:
        raise OnuParseError(f"Status page is missing fields: {', '.join(sorted(missing))}")

    values: dict[str, str | float | int | None] = {}
    for label, key in fields.items():
        raw = parser.rows[label]
        if raw.casefold() in _UNKNOWN_VALUES:
            values[key] = None
            continue
        if key not in _NUMBER_UNITS:
            values[key] = raw
            continue
        match = re.fullmatch(
            rf"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:{_NUMBER_UNITS[key]})?",
            raw,
            re.IGNORECASE,
        )
        if not match:
            raise OnuParseError(f"Invalid number for {label}")
        number = float(match[1])
        if not math.isfinite(number):
            raise OnuParseError(f"Non-finite number for {label}")
        if key == "onu_id":
            if number < 0 or not number.is_integer():
                raise OnuParseError("Invalid ONU ID")
            values[key] = int(number)
        else:
            values[key] = number
    return values


@dataclass(frozen=True)
class OnuStatus:
    """One complete poll of both status pages."""

    values: dict[str, str | float | int | None]
    mac_address: str


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


class OnuClient:
    """Read status pages and submit only the firmware's authentication form."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str = "",
        password: str = "",
    ) -> None:
        self._session = session
        self.host = normalize_host(host)
        self._username = username
        self._password = password
        self._lock = asyncio.Lock()
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
            headers["Referer"] = f"{self.host}{LOGIN_PAGE_PATH}"
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

    async def _async_read_status(self) -> OnuStatus:
        """Use sequential requests to keep the embedded server's load low."""
        device = parse_status_page(await self._request("GET", DEVICE_STATUS_PATH), DEVICE_FIELDS)
        pon = parse_status_page(await self._request("GET", PON_STATUS_PATH), PON_FIELDS)
        mac = device["mac_address"]
        if not isinstance(mac, str) or not device["device_name"]:
            raise OnuParseError("Device identity is missing")
        return OnuStatus(values={**device, **pon}, mac_address=normalize_mac(mac))

    async def async_get_status(self) -> OnuStatus:
        """Reuse login state, and authenticate at most once per poll if needed."""
        async with self._lock:
            try:
                return await self._async_read_status()
            except _OnuLoginRequired:
                await self._async_login()
                try:
                    return await self._async_read_status()
                except _OnuLoginRequired as err:
                    raise OnuAuthError(
                        "Login was rejected. Check the username and password"
                    ) from err
