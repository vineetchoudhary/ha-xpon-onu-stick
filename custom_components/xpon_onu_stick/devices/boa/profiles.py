"""Small, evidence-backed Boa firmware differences, independent of hardware branding."""

from dataclasses import dataclass

from ...models import OnuParseError


@dataclass(frozen=True)
class BoaProfile:
    """Override field expectations only when captured firmware demonstrates a difference."""

    id: str
    firmware_version: str | None = None
    pon_mode: str | None = None
    optional_fields: frozenset[str] = frozenset()
    unsupported_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if "mac_address" in self.optional_fields | self.unsupported_fields:
            raise ValueError("MAC identity must remain required in every profile")
        if self.optional_fields & self.unsupported_fields:
            raise ValueError("A field cannot be both optional and unsupported")


DEFAULT_PROFILE = BoaProfile("boa")
PROFILES = (
    # tests/fixtures/devices/bdcom-unknown-model/V2.11.00P3T1/
    # The visible tables omit Device Name. This is not a rule for every EPON ONU.
    BoaProfile(
        "boa-epon-v2.11.00p3t1",
        firmware_version="V2.11.00P3T1",
        pon_mode="epon",
        optional_fields=frozenset({"device_name"}),
    ),
)


def select_profile(firmware_version: str | float | int | None, pon_mode: str) -> BoaProfile:
    """Use page-detected mode and exact firmware evidence, with a generic fallback."""
    matches = [
        profile
        for profile in PROFILES
        if (profile.firmware_version is None or profile.firmware_version == firmware_version)
        and (profile.pon_mode is None or profile.pon_mode == pon_mode)
    ]
    if len(matches) > 1:
        raise OnuParseError("Ambiguous Boa firmware profile")
    return matches[0] if matches else DEFAULT_PROFILE
