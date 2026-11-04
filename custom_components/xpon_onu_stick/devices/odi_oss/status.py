"""Parse the read-only ODI OSS v1.15.0 GPON and system telemetry."""

import re
from collections.abc import Callable
from ipaddress import IPv4Interface

from ...models import OnuCapabilities, OnuParseError, OnuStatus, normalize_mac

# Filter GPON status on the stick so its serial, Alloc-IDs and ranging details
# never reach Home Assistant. Nothing from the configuration or output is
# interpolated into this command.
STATUS_READS = {
    "build": """awk -F= '$1 == "image" || $1 == "kernel"' /etc/odi-build""",
    "mac": "cat /sys/class/net/br0/address",
    "gpon": """awk '$1 == "state" || $1 == "onu_id" ||
        ($2 == "los" && ($1 == "alarm_events" || $1 == "alarm_ms"))' /proc/odi_gpon/status""",
    "optics": "/bin/diag pon get transceiver all",
    "alarms": "/bin/diag pon get transceiver alarm-status",
    "counters": """awk '$1 == "ctr" && $2 ~ /^(ds_bip_err_blocks|ds_fec_corrected_cw|ds_fec_uncorrectable_cw)$/' /proc/odi_gpon/counters""",
    "uptime": "cat /proc/uptime",
    "cpu": """awk 'NR == 1 {print; exit}' /proc/stat""",
    "memory": """awk '$1 == "MemTotal:" || $1 == "MemAvailable:"' /proc/meminfo""",
    "ipv4": """ip -4 -o addr show dev br0 | awk '$3 == "inet" {
        for (i = 5; i <= NF; i++) if ($i ~ /^br0([^a-zA-Z0-9_:]|$)/) {print $4; break}
    }'""",
}
_PREFIX = "XPON-ODI-STATUS "
STATUS_COMMAND = "\n".join(
    ["export LC_ALL=C"]
    + [f"printf '%s\\n' '{_PREFIX}{name}'; {read}" for name, read in STATUS_READS.items()]
    + [f"printf '%s\\n' '{_PREFIX}end'"]
)

_OPTICS = {
    "temperature": ("Temperature", "C"),
    "voltage": ("Voltage", "V"),
    "bias_current": ("Bias Current", "mA"),
    "tx_power": ("Tx Power", "dBm"),
    "rx_power": ("Rx Power", "dBm"),
}
_COUNTERS = {
    "gpon_ds_bip_error_blocks": "ds_bip_err_blocks",
    "gpon_ds_fec_corrected_codewords": "ds_fec_corrected_cw",
    "gpon_ds_fec_uncorrectable_codewords": "ds_fec_uncorrectable_cw",
}
COUNTER_KEYS = (*_COUNTERS, "gpon_los_events", "gpon_los_duration")
ALARM_KEYS = ("optical_los", "optical_ddm_alarm", "optical_ddm_warning")
_CAPABILITIES = OnuCapabilities(
    frozenset(
        {
            "device_name",
            "firmware_version",
            "mac_address",
            "onu_state",
            "onu_id",
            "uptime",
            "cpu_usage",
            "memory_usage",
            "ip_address",
            "subnet_mask",
            *_OPTICS,
            *COUNTER_KEYS,
            *ALARM_KEYS,
        }
    )
)

type Reading = str | float | int | bool | None


def _sections(output: str) -> dict[str, str]:
    sections = re.split(rf"(?m)^{_PREFIX}([a-z0-9]+)\n", output)
    if sections[0] or sections[1::2] != [*STATUS_READS, "end"] or sections[-1].strip():
        raise OnuParseError("The SSH reply does not contain a complete ODI OSS status response")
    return dict(zip(sections[1:-2:2], sections[2:-2:2], strict=True))


def _row(section: str, label: str, separator: str = " ") -> str:
    matches = re.findall(rf"(?m)^{re.escape(label + separator)}([^\n]*)$", section)
    if len(matches) != 1:
        raise ValueError("Expected one field")
    return matches[0].strip()


def _uint(raw: str) -> int:
    if not re.fullmatch(r"[0-9]{1,20}", raw) or (value := int(raw)) >= 2**64:
        raise ValueError("Expected an unsigned 64-bit integer")
    return value


def _onu_id(raw: str) -> int:
    value = _uint(raw)
    if value > 255:
        raise ValueError("Invalid GPON ONU ID")
    return value


def _state(raw: str) -> str:
    match = re.fullmatch(r"([1-7]) \(O\1\)", raw)
    if not match:
        raise ValueError("Invalid GPON state")
    return f"O{match[1]}"


def _measurement(raw: str, unit: str) -> float | None:
    if raw.casefold() in {"", "-", "--", "n/a", "na", "unknown", "not available"}:
        return None
    match = re.fullmatch(rf"([+-]?[0-9]{{1,16}}(?:\.[0-9]{{1,16}})?)\s*{unit}", raw)
    if not match:
        raise ValueError("Invalid optical value or unit")
    return float(match[1])


def _flag(raw: str) -> bool:
    if raw not in {"clear", "occur"}:
        raise ValueError("Invalid alarm flag")
    return raw == "occur"


def _ddm_flag(section: str, severity: str) -> bool:
    flags = [
        _flag(_row(section, f"{severity} {label} {limit}", ", status: "))
        for label, _ in _OPTICS.values()
        for limit in ("high", "low")
    ]
    return any(flags)


def _memory(section: str) -> float:
    def kib(label: str) -> int:
        value, unit = _row(section, label, ":").split()
        if unit != "kB":
            raise ValueError("Invalid memory unit")
        return _uint(value)

    total = kib("MemTotal")
    available = kib("MemAvailable")
    if not total or available > total:
        raise ValueError("Invalid available memory")
    return (total - available) / total * 100


def _uptime(section: str) -> int:
    seconds, _idle = section.split()
    whole, dot, fraction = seconds.partition(".")
    if dot and not re.fullmatch(r"[0-9]{1,6}", fraction):
        raise ValueError("Invalid uptime")
    return _uint(whole)


def _address(section: str) -> IPv4Interface:
    value = section.strip()
    if not re.fullmatch(r"[0-9.]{7,15}/[0-9]{1,2}", value):
        raise ValueError("Expected one IPv4 address and prefix length")
    return IPv4Interface(value)


class OdiStatusParser:
    """Convert one poll at a time and retain the last valid CPU sample."""

    def __init__(self) -> None:
        self._cpu_sample: tuple[int, ...] | None = None
        self._uptime: int | None = None

    def _cpu(self, section: str, uptime: int | None) -> float | None:
        try:
            raw = _row(section, "cpu").split()
            if len(raw) < 8 or uptime is None:
                raise ValueError("Incomplete CPU sample")
            # guest/guest_nice are already included in user/nice.
            current = tuple(_uint(counter) for counter in raw[:8])
        except ValueError:
            self._cpu_sample = None
            raise
        previous, self._cpu_sample = self._cpu_sample, current
        previous_uptime, self._uptime = self._uptime, uptime
        if previous is None or previous_uptime is None or uptime < previous_uptime:
            return None
        deltas = [value - old for value, old in zip(current, previous, strict=True)]
        total = sum(deltas)
        if min(deltas) < 0 or total == 0:
            return None
        return (total - deltas[3] - deltas[4]) / total * 100

    def parse(self, output: str) -> OnuStatus:
        """Validate firmware, GPON structure and identity before accepting any readings."""
        sections = _sections(output)
        try:
            version = _row(sections["build"], "image", "=")
            kernel = _row(sections["build"], "kernel", "=")
            if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", version) or not re.fullmatch(
                r"[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.+_-]*", kernel
            ):
                raise ValueError("Invalid firmware build metadata")
        except ValueError as err:
            raise OnuParseError("The SSH reply does not identify an ODI OSS build") from err
        gpon = sections["gpon"]
        if not re.search(r"(?m)^(state|onu_id) ", gpon):
            raise OnuParseError("The SSH reply does not contain ODI OSS GPON status")
        identity = sections["mac"].strip()
        if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", identity):
            raise OnuParseError("Invalid ODI OSS management MAC address")
        mac = normalize_mac(identity)
        values: dict[str, Reading] = {
            "device_name": "ODI OSS",
            "firmware_version": version,
            "mac_address": mac,
        }
        errors: dict[str, str] = {}

        def read[T: Reading](key: str, parse: Callable[[], T]) -> T | None:
            try:
                value = parse()
            except ValueError:
                errors[key] = f"Missing or invalid ODI OSS reading for {key}"
                value = None
            values[key] = value
            return value

        read("onu_state", lambda: _state(_row(gpon, "state")))
        read("onu_id", lambda: _onu_id(_row(gpon, "onu_id")))
        for key, (label, unit) in _OPTICS.items():
            read(
                key,
                lambda label=label, unit=unit: _measurement(
                    _row(sections["optics"], label, ":"), unit
                ),
            )
        alarms = sections["alarms"]
        read("optical_los", lambda: _flag(_row(alarms, "Optical LOS", ", status: ")))
        read("optical_ddm_alarm", lambda: _ddm_flag(alarms, "Alarm"))
        read("optical_ddm_warning", lambda: _ddm_flag(alarms, "Warning"))
        for key, counter in _COUNTERS.items():
            read(key, lambda counter=counter: _uint(_row(sections["counters"], f"ctr {counter}")))
        read("gpon_los_events", lambda: _uint(_row(gpon, "alarm_events los")))
        read("gpon_los_duration", lambda: _uint(_row(gpon, "alarm_ms los")) / 1000)
        uptime = read("uptime", lambda: _uptime(sections["uptime"]))
        if uptime is not None:
            hours, remainder = divmod(uptime, 3600)
            minutes, seconds = divmod(remainder, 60)
            values["uptime"] = f"{hours}:{minutes:02d}:{seconds:02d}"
        read("cpu_usage", lambda: self._cpu(sections["cpu"], uptime))
        read("memory_usage", lambda: _memory(sections["memory"]))
        read("ip_address", lambda: str(_address(sections["ipv4"]).ip))
        read("subnet_mask", lambda: str(_address(sections["ipv4"]).netmask))
        return OnuStatus(values, mac, field_errors=errors, capabilities=_CAPABILITIES)
