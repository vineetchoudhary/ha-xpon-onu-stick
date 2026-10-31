"""Home Assistant-independent status, capabilities, request policy, and errors."""

import re
from dataclasses import dataclass, field

GPON_READING_KEYS = frozenset({"onu_state", "onu_id", "loid_status"})


class OnuError(Exception):
    """Base error from the ONU client."""


class OnuConnectionError(OnuError):
    """The status interface could not be reached."""


class OnuAuthError(OnuError):
    """The status interface requires authentication."""


class OnuSessionBusy(OnuError):
    """The firmware refused login because another management session is active."""


class OnuLoginRequired(OnuAuthError):
    """The firmware requested a new browser login session."""


class OnuParseError(OnuError):
    """A response is not a supported status page."""


class OnuLogoutError(OnuError):
    """The ONU did not confirm that its management session was closed."""


def normalize_mac(value: str) -> str:
    """Create a stable identity from the device's MAC address."""
    compact = re.sub(r"[:.\-]", "", value).lower()
    if not re.fullmatch(r"[0-9a-f]{12}", compact):
        raise OnuParseError("Invalid MAC address on Device Status page")
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


@dataclass(frozen=True)
class HttpPolicy:
    """Reviewed request methods/paths and POST referers for one interface family."""

    allowed_requests: frozenset[tuple[str, str]]
    post_referers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class OnuCapabilities:
    """Supported readings and fields that this firmware may intentionally omit."""

    fields: frozenset[str]
    optional_fields: frozenset[str] = frozenset()


@dataclass(frozen=True)
class OnuStatus:
    """One poll of both pages, with invalid readings isolated by field."""

    values: dict[str, str | float | int | None]
    mac_address: str
    pon_mode: str = "gpon"
    field_errors: dict[str, str] = field(default_factory=dict)
    profile_id: str | None = None
    capabilities: OnuCapabilities | None = None

    def supports(self, key: str) -> bool:
        """Distinguish an unsupported field from a supported but invalid reading."""
        return self.capabilities is None or key in self.capabilities.fields

    @property
    def name(self) -> str:
        """Use a stable display name when EPON firmware omits Device Name."""
        fallback = (
            f"XPON ONU {self.mac_address}"
            if self.pon_mode == "epon"
            else f"XPON ONU Stick ({self.mac_address})"
        )
        return str(self.values.get("device_name") or fallback)
