"""Bounded, host-verified SSH transport for ODI OSS."""

import asyncio
import logging
import os
import re
import stat
from contextlib import ExitStack
from hmac import compare_digest
from ipaddress import ip_address
from pathlib import Path
from time import time
from weakref import WeakValueDictionary

import asyncssh

from ...const import REQUEST_TIMEOUT
from ...models import (
    OnuAuthError,
    OnuConnectionError,
    OnuParseError,
    OnuStatus,
    report_field_errors,
)
from .status import STATUS_COMMAND, OdiStatusParser

_LOGGER = logging.getLogger(__name__)
_LOCKS: WeakValueDictionary[tuple[asyncio.AbstractEventLoop, str, int], asyncio.Lock] = (
    WeakValueDictionary()
)
_MAX_KEY_BYTES = 16 * 1024
_MAX_REPLY_BYTES = 256 * 1024
_HOST_KEY_ALGORITHM = "ssh-ed25519"
_READ_CLOCK = "/bin/busybox date -u +%s"
_CLOCK_CHECK_INTERVAL = 300
_CLOCK_TOLERANCE = 60
_CLOCK_TIMEOUT = 5
_MIN_HOME_EPOCH = 946684800  # 2000-01-01 UTC


class OnuHostKeyError(OnuConnectionError):
    """The server did not present the configured SSH host key."""


class OnuKeyFileError(OnuAuthError):
    """Home Assistant could not load the selected SSH key file."""


def normalize_ssh_host(host: str) -> str:
    """Accept only an IP address or DNS hostname, separate from the SSH port."""
    host = host.strip()
    if "%" not in host:
        try:
            return str(ip_address(host))
        except ValueError:
            pass
    hostname = host.encode("idna").decode().lower().removesuffix(".")
    if not 0 < len(hostname) <= 253 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in hostname.split(".")
    ):
        raise ValueError("Invalid SSH hostname")
    return hostname


def normalize_fingerprint(fingerprint: str) -> str:
    fingerprint = fingerprint.strip()
    if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]", fingerprint):
        raise ValueError("Expected an OpenSSH SHA-256 fingerprint")
    return fingerprint


def _read_key(config_dir: str, filename: str) -> asyncssh.SSHKey:
    """Load a private file beneath the configuration directory without following links."""
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", filename):
        raise OnuKeyFileError("Enter the filename of a private key in xpon_onu_stick/ssh/")
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        with ExitStack() as stack:
            directory_fd = os.open(Path(config_dir).resolve(), flags)
            stack.callback(os.close, directory_fd)
            for directory in ("xpon_onu_stick", "ssh"):
                directory_fd = os.open(directory, flags, dir_fd=directory_fd)
                stack.callback(os.close, directory_fd)
            key_fd = os.open(
                filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
            )
            key_file = stack.enter_context(os.fdopen(key_fd, "rb"))
            metadata = os.fstat(key_file.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise ValueError("Expected a private regular file")
            data = key_file.read(_MAX_KEY_BYTES + 1)
        if len(data) > _MAX_KEY_BYTES:
            raise ValueError("SSH key exceeds size limit")
        key = asyncssh.import_private_key(data)
        if key.get_algorithm() != _HOST_KEY_ALGORITHM:
            raise ValueError("Expected an Ed25519 private key")
        return key
    except OSError, ValueError:
        raise OnuKeyFileError(
            "Cannot load SSH key. Use an unencrypted Ed25519 private key file with mode 0600"
        ) from None


class _PinnedHost(asyncssh.SSHClient):
    def __init__(self, fingerprint: str) -> None:
        self._fingerprint = fingerprint

    def validate_host_public_key(
        self, host: str, addr: str, port: int, key: asyncssh.SSHKey
    ) -> bool:
        return compare_digest(key.get_fingerprint("sha256"), self._fingerprint)


class OdiSshClient:
    """Own one SSH connection and reuse it for sequential status polls."""

    def __init__(
        self, host: str, port: int, config_dir: str, key_filename: str, fingerprint: str
    ) -> None:
        self.host = host
        self.port = port
        self._config_dir = config_dir
        self._key_filename = key_filename
        self._fingerprint = fingerprint
        self._connection: asyncssh.SSHClientConnection | None = None
        self._lock = _LOCKS.setdefault((asyncio.get_running_loop(), host, port), asyncio.Lock())
        self._parser = OdiStatusParser()
        self._field_errors: dict[str, str] = {}
        self._next_clock_check = 0.0
        self._clock_sync_failed = False

    async def _async_connect(self) -> asyncssh.SSHClientConnection:
        key = await asyncio.to_thread(_read_key, self._config_dir, self._key_filename)
        return await asyncssh.connect(
            self.host,
            self.port,
            username="root",
            config=None,
            client_keys=[key],
            agent_path=None,
            agent_forwarding=False,
            gss_host=None,  # Require the pinned host key during key exchange.
            preferred_auth=["publickey"],
            disable_trivial_auth=True,
            known_hosts=((), (), ()),
            server_host_key_algs=[_HOST_KEY_ALGORITHM],
            client_factory=lambda: _PinnedHost(self._fingerprint),
        )

    async def _async_read(self) -> str:
        if self._connection is None or self._connection.is_closed():
            self._parser = OdiStatusParser()
            self._connection = await self._async_connect()
            if not self._clock_sync_failed:
                self._next_clock_check = 0.0
        return await self._async_run(self._connection, STATUS_COMMAND)

    async def _async_run(self, connection: asyncssh.SSHClientConnection, command: str) -> str:
        process = await connection.create_process(
            command, encoding=None, request_pty=False, stderr=asyncssh.STDOUT
        )
        try:
            process.stdin.write_eof()
            try:
                await process.stdout.readexactly(_MAX_REPLY_BYTES + 1)
            except asyncio.IncompleteReadError as err:
                output = err.partial
            else:
                raise OnuConnectionError("ODI OSS SSH status exceeded the response size limit")
            await process.wait_closed()
            if process.exit_status != 0:
                raise OnuConnectionError("ODI OSS SSH status command failed")
            return output.decode("utf-8", errors="replace")
        finally:
            process.close()

    async def _async_sync_clock(self, connection: asyncssh.SSHClientConnection) -> None:
        now = asyncio.get_running_loop().time()
        if now < self._next_clock_check:
            return
        self._next_clock_check = now + _CLOCK_CHECK_INTERVAL
        try:
            async with asyncio.timeout(_CLOCK_TIMEOUT):
                current = (await self._async_run(connection, _READ_CLOCK)).strip()
                host_epoch = int(time())
                if not re.fullmatch(r"[0-9]{1,12}", current) or host_epoch < _MIN_HOME_EPOCH:
                    raise ValueError("Invalid clock time")
                if abs(int(current) - host_epoch) > _CLOCK_TOLERANCE:
                    # BusyBox can report success even if the set failed. Read
                    # the actual clock back and only interpolate HA's integer.
                    command = f"/bin/busybox date -u -s @{host_epoch} >/dev/null && {_READ_CLOCK}"
                    updated = (await self._async_run(connection, command)).strip()
                    if not re.fullmatch(r"[0-9]{1,12}", updated) or (
                        abs(int(updated) - host_epoch) > _CLOCK_TOLERANCE
                    ):
                        raise ValueError("Clock update could not be verified")
        except asyncssh.Error, OSError, OnuConnectionError, ValueError:
            if not self._clock_sync_failed:
                _LOGGER.warning("Could not sync the ODI OSS clock at %s", self.host)
            self._clock_sync_failed = True
        else:
            self._clock_sync_failed = False

    def _abort(self) -> None:
        if self._connection is not None:
            self._connection.abort()
            self._connection = None

    async def async_get_status(self, *, sync_clock_for_mac: str | None = None) -> OnuStatus:
        async with self._lock:
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    output = await self._async_read()
            except asyncssh.HostKeyNotVerifiable:
                self._abort()
                raise OnuHostKeyError(
                    "ODI OSS SSH host key mismatch. Verify the fingerprint and reconfigure"
                ) from None
            except asyncssh.PermissionDenied:
                self._abort()
                raise OnuAuthError("ODI OSS rejected the SSH client key") from None
            except asyncssh.Error, OSError:
                self._abort()
                raise OnuConnectionError("Could not read ODI OSS status over SSH") from None
            except asyncio.CancelledError, OnuConnectionError:
                self._abort()
                raise
            try:
                status = self._parser.parse(output)
            except OnuParseError:
                self._abort()
                raise
            report_field_errors(self._field_errors, status, _LOGGER, self.host)
            self._field_errors = status.field_errors.copy()
            if status.mac_address == sync_clock_for_mac and self._connection is not None:
                await self._async_sync_clock(self._connection)
            return status

    async def async_close(self) -> None:
        """Release this client's connection on validation exit, unload or shutdown."""
        async with self._lock:
            connection, self._connection = self._connection, None
            if connection is not None:
                connection.abort()
                await connection.wait_closed()
