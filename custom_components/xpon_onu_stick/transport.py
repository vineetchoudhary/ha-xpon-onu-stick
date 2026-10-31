"""HTTP safety and per-origin serialization shared by all device adapters."""

import asyncio
from collections.abc import Callable
from weakref import WeakValueDictionary

import aiohttp
from yarl import URL

from .const import REQUEST_TIMEOUT
from .models import HttpPolicy, OnuAuthError, OnuConnectionError, OnuLoginRequired, OnuParseError

_DEVICE_LOCKS: WeakValueDictionary[tuple[asyncio.AbstractEventLoop, str], asyncio.Lock] = (
    WeakValueDictionary()
)
_MAX_RESPONSE_BYTES = 256 * 1024


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


class OnuTransport:
    """Enforce the selected adapter's reviewed request policy on one device origin."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        policy: HttpPolicy,
    ) -> None:
        self.session = session
        self.host = normalize_host(host)
        self.policy = policy
        lock_key = (asyncio.get_running_loop(), self.host)
        self.lock = _DEVICE_LOCKS.setdefault(lock_key, asyncio.Lock())
        # Cookies belong to this client, never to Home Assistant's shared session.
        self.cookie_jar = aiohttp.CookieJar(unsafe=True)
        try:
            self._headers = (
                {"Authorization": aiohttp.encode_basic_auth(username, password)} if username else {}
            )
        except ValueError as err:
            raise OnuAuthError("Invalid HTTP Basic credentials") from err

    def _url(self, path: str) -> URL:
        """Even a future adapter policy cannot turn a path into a foreign URL."""
        try:
            url = URL(path)
        except ValueError as err:
            raise OnuConnectionError("Unsupported ONU request") from err
        if (
            not path.startswith("/")
            or path.startswith("//")
            or url.is_absolute()
            or url.query_string
            or url.fragment
            or url.path != path
            or any(part in {".", ".."} for part in url.path.split("/"))
        ):
            raise OnuConnectionError("Unsupported ONU request")
        return URL(self.host).join(url)

    def _redirect_path(self, location: str) -> str | None:
        try:
            origin = URL(self.host)
            target = origin.join(URL(location))
            if (
                target.origin() == origin
                and target.user is None
                and target.password is None
                and not target.query_string
                and not target.fragment
            ):
                return target.path
        except ValueError:
            pass
        return None

    async def request(
        self,
        method: str,
        path: str,
        data: dict[str, str] | None,
        *,
        validate_response: Callable[[int, str | None], None],
        is_login_error: Callable[[int, str], bool],
    ) -> str:
        """Perform a bounded request and delegate interface-specific auth recognition."""
        if method not in {"GET", "POST"} or (method, path) not in self.policy.allowed_requests:
            raise OnuConnectionError("Unsupported ONU request")
        url = self._url(path)
        headers = dict(self._headers)
        kwargs = {}
        if method == "POST":
            if referer := dict(self.policy.post_referers).get(path):
                headers["Referer"] = str(self._url(referer))
            kwargs["data"] = data
        request = self.session.get if method == "GET" else self.session.post
        try:
            async with request(
                url,
                headers=headers,
                cookies=self.cookie_jar.filter_cookies(url),
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                allow_redirects=False,
                **kwargs,
            ) as response:
                self.cookie_jar.update_cookies(response.cookies, response_url=url)
                if response.status in {401, 403}:
                    raise OnuAuthError("Authentication is required or credentials are invalid")
                validate_response(
                    response.status, self._redirect_path(response.headers.get("Location", ""))
                )
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.content.iter_chunked(16 * 1024):
                    body.extend(chunk)
                    if len(body) > _MAX_RESPONSE_BYTES:
                        raise OnuParseError("The ONU response exceeds the supported page size")
                try:
                    return body.decode(response.charset or "utf-8", errors="replace")
                except LookupError:
                    return body.decode("utf-8", errors="replace")
        except aiohttp.ClientResponseError as err:
            if is_login_error(err.status, err.message):
                raise OnuLoginRequired("The status endpoint requested login") from err
            raise OnuConnectionError(f"Unable to read {path}") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise OnuConnectionError(f"Unable to read {path}") from err
