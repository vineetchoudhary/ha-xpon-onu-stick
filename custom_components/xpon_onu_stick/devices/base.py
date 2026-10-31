"""The small contract between shared polling and a device interface implementation."""

from typing import Protocol

from ..models import HttpPolicy, OnuStatus


class OnuRequest(Protocol):
    """Only the shared transport may perform adapter requests."""

    async def __call__(self, method: str, path: str, data: dict[str, str] | None = None) -> str: ...


class DeviceAdapter(Protocol):
    """Implement interface differences without importing Home Assistant or owning HTTP."""

    policy: HttpPolicy
    login_page_path: str
    login_form_path: str
    logout_form_path: str

    async def async_read_status(self, request: OnuRequest) -> OnuStatus: ...

    def login_payload(
        self, html: str, host: str, username: str, password: str
    ) -> dict[str, str]: ...

    def login_result(self, html: str) -> tuple[bool, bool]: ...

    def logout_payload(self) -> dict[str, str]: ...

    def validate_logout(self, html: str) -> None: ...

    def validate_response(
        self, method: str, path: str, status: int, redirect_path: str | None
    ) -> None: ...

    def is_login_error(self, status: int, message: str) -> bool: ...
