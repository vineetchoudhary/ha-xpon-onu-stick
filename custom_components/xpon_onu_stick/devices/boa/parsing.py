"""Parse the captured Boa status tables and GPON/EPON formats without I/O."""

import math
import re
from html.parser import HTMLParser

from ...models import OnuLoginRequired, OnuParseError

_MAX_LLID_INTEGER_DIGITS = 64


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


def _parse_llid_integer(raw: str, label: str) -> int:
    """Bound numeric firmware text independently of Python's conversion limit."""
    try:
        if len(raw) > _MAX_LLID_INTEGER_DIGITS or not re.fullmatch(r"[0-9]+", raw):
            raise ValueError("Expected a bounded nonnegative integer")
        return int(raw)
    except ValueError as err:
        preview = raw if len(raw) <= 80 else raw[:80] + "..."
        raise OnuParseError(f"Invalid EPON LLID {label}: {preview!r}") from err


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
        raise OnuLoginRequired("The device returned a login form")
    if re.search(r"href\s*=\s*['\"]?/admin/login\.asp(?:['\"\s>])", html, re.IGNORECASE):
        raise OnuLoginRequired("The device requested login")
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
        if len(row) != 2:
            raise OnuParseError("Invalid EPON LLID index")
        index = _parse_llid_integer(row[0], "index")
        key = f"epon_llid_{index}_status"
        if key in values:
            raise OnuParseError("Duplicate EPON LLID index")
        raw = row[1]
        if raw.casefold() in _UNKNOWN_VALUES:
            values[key] = None
        else:
            try:
                # Preserve firmware codes; they are not GPON O1–O7 states.
                values[key] = _parse_llid_integer(raw, f"status for index {index}")
            except OnuParseError as err:
                values[key] = None
                if field_errors is not None:
                    field_errors[key] = str(err)
    return "epon", values
