"""Test real captured HTML and transport boundaries."""

import asyncio
import logging
import re
from unittest.mock import patch

import aiohttp
import pytest

from custom_components.xpon_onu_stick.api import (
    DEVICE_FIELDS,
    PON_FIELDS,
    OnuAuthError,
    OnuClient,
    OnuConnectionError,
    OnuParseError,
    normalize_host,
    normalize_mac,
    parse_status_page,
)


def test_live_device_fixture(device_html):
    values = parse_status_page(device_html, DEVICE_FIELDS)
    assert len(values) == 8
    assert values["device_name"] == "AOT5222ZY"
    assert values["firmware_version"] == "V1.0-220923"
    assert values["uptime"] == "1:21"
    assert values["cpu_usage"] == 0.0
    assert values["memory_usage"] == 50.0
    assert values["ip_address"] == "192.0.2.1"
    assert values["subnet_mask"] == "255.255.255.0"
    assert values["mac_address"] == "020000000001"


def test_live_pon_fixture(pon_html):
    values = parse_status_page(pon_html, PON_FIELDS)
    assert values == {
        "temperature": 37.277344,
        "voltage": 3.2561,
        "tx_power": 1.9399,
        "rx_power": -26.382721,
        "bias_current": 11.15,
        "onu_state": "O5",
        "onu_id": 0,
        "loid_status": "Initial Status",
    }


@pytest.mark.parametrize("raw", ["", "-", "--", "N/A", "unknown"])
def test_unknown_reading_is_not_zero(pon_html, raw):
    html = pon_html.replace("-26.382721  dBm", raw)
    errors = {}
    assert parse_status_page(html, PON_FIELDS, field_errors=errors)["rx_power"] is None
    assert errors == {}


@pytest.mark.parametrize(
    "raw", ["NaN", "Infinity", "-inf V", "bad", "3.24 mA", "3.24 V corrupt", "9" * 400]
)
def test_invalid_numeric_data(pon_html, raw):
    errors = {}
    values = parse_status_page(pon_html.replace("3.256100 V", raw), PON_FIELDS, field_errors=errors)
    assert values == {**parse_status_page(pon_html, PON_FIELDS), "voltage": None}
    assert set(errors) == {"voltage"}
    assert "number for voltage" in errors["voltage"]


@pytest.mark.parametrize("raw", ["-1", "0.5", "NaN", "bad"])
def test_invalid_onu_id_does_not_discard_other_readings(pon_html, raw):
    html = pon_html.replace("<font size=2>0</td>", f"<font size=2>{raw}</td>")
    errors = {}
    values = parse_status_page(html, PON_FIELDS, field_errors=errors)
    assert values == {**parse_status_page(pon_html, PON_FIELDS), "onu_id": None}
    assert set(errors) == {"onu_id"}


@pytest.mark.parametrize(
    "fixture_name, fields, key, previous, unit",
    [
        ("device_html", DEVICE_FIELDS, "cpu_usage", "0%", "%"),
        ("device_html", DEVICE_FIELDS, "memory_usage", "50%", "%"),
        ("pon_html", PON_FIELDS, "temperature", "37.277344 C", "C"),
        ("pon_html", PON_FIELDS, "voltage", "3.256100 V", "V"),
        ("pon_html", PON_FIELDS, "tx_power", "1.939900  dBm", "dBm"),
        ("pon_html", PON_FIELDS, "rx_power", "-26.382721  dBm", "dBm"),
        ("pon_html", PON_FIELDS, "bias_current", "11.150000 mA", "mA"),
        ("pon_html", PON_FIELDS, "onu_id", "0", ""),
    ],
)
@pytest.mark.parametrize("raw", ["inf", "-inf", "+Infinity", "NaN", "-nan", "nan(0x123)"])
def test_non_finite_formats_are_isolated_for_every_numeric_field(
    request, fixture_name, fields, key, previous, unit, raw
):
    original = request.getfixturevalue(fixture_name)
    html = original.replace(f">{previous}<", f">{raw} {unit}<", 1)
    assert html != original
    errors = {}
    values = parse_status_page(html, fields, field_errors=errors)
    assert values == {**parse_status_page(original, fields), key: None}
    assert set(errors) == {key}


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0", 0.0),
        ("+0.0 dBm", 0.0),
        ("-0.0 dBm", 0.0),
        ("-40.000000 dBm", -40.0),
        ("+.5 DBM", 0.5),
        ("1.dBm", 1.0),
        ("-26.5&nbsp;dBm", -26.5),
    ],
)
def test_finite_optical_formats_keep_actual_values(raw, expected):
    errors = {}
    html = f"<table><tr><td>Rx Power</td><td>{raw}</td></tr></table>"
    assert parse_status_page(html, {"rx power": "rx_power"}, field_errors=errors) == {
        "rx_power": expected
    }
    assert errors == {}


@pytest.mark.parametrize("raw", ["0", "254", "255"])
def test_onu_ids_including_unassigned_value_are_preserved(pon_html, raw):
    html = pon_html.replace(">0<", f">{raw}<")
    assert parse_status_page(html, PON_FIELDS)["onu_id"] == int(raw)


@pytest.mark.parametrize(
    "fixture_name, fields", [("device_html", DEVICE_FIELDS), ("pon_html", PON_FIELDS)]
)
def test_each_missing_field_is_isolated(request, fixture_name, fields):
    html = request.getfixturevalue(fixture_name)
    baseline = parse_status_page(html, fields)
    for label, key in fields.items():
        errors = {}
        # Changing the label simulates a missing or unsupported firmware row.
        changed = re.sub(re.escape(label), "Unsupported Field", html, flags=re.IGNORECASE)
        values = parse_status_page(changed, fields, field_errors=errors)
        assert values == {**baseline, key: None}, key
        assert errors == {key: f"Status page is missing field: {label}"}


def test_missing_fields_and_commented_rows(pon_html):
    assert (
        parse_status_page(pon_html.replace("Rx Power", "Receive Power"), PON_FIELDS)["rx_power"]
        is None
    )
    html = "<!-- <tr><td>Rx Power</td><td>0 dBm</td></tr> -->" + pon_html
    assert parse_status_page(html, PON_FIELDS)["rx_power"] == -26.382721


def test_html_entities_and_incomplete_cells():
    html = "<table><tr><td><b>Rx&nbsp; Power:</b><td><font>-26.5&nbsp;dBm</tr></table>"
    assert parse_status_page(html, {"rx power": "rx_power"}) == {"rx_power": -26.5}


@pytest.mark.parametrize("html", ['<input type="password">', "<INPUT TYPE=password NAME=pass>"])
def test_form_login_detected(html):
    with pytest.raises(OnuAuthError):
        parse_status_page(html, DEVICE_FIELDS)


@pytest.mark.parametrize(
    "host, expected",
    [
        ("192.0.2.1", "http://192.0.2.1"),
        (" http://192.0.2.1/ ", "http://192.0.2.1"),
        ("https://onu.local:8443/", "https://onu.local:8443"),
        ("http://[::1]/", "http://[::1]"),
    ],
)
def test_normalize_host(host, expected):
    assert normalize_host(host) == expected


@pytest.mark.parametrize(
    "host",
    [
        "",
        "ftp://onu",
        "http://user:pass@onu",
        "http://onu/settings.asp",
        "http://onu/?action=reboot",
        "http://onu/#settings",
        "http://onu:bad",
        "some host",
    ],
)
def test_unsafe_or_invalid_hosts_rejected(host):
    with pytest.raises(ValueError):
        normalize_host(host)


def test_mac_identity():
    assert normalize_mac("020000000001") == "02:00:00:00:00:01"
    assert normalize_mac("02:00:00:00:AB:01") == "02:00:00:00:ab:01"
    with pytest.raises(OnuParseError):
        normalize_mac("not-a-mac")


async def test_client_reads_two_pages_without_logging_out_by_default(onu_server):
    host, _, requests = onu_server
    async with aiohttp.ClientSession() as session:
        status = await OnuClient(session, host).async_get_status()
    assert len(status.values) == 16
    assert status.mac_address == "02:00:00:00:00:01"
    assert requests == [
        ("GET", "/status.asp", None),
        ("GET", "/status_pon.asp", None),
    ]


async def test_outage_errors_are_logged_once_and_reset_after_recovery(
    onu_server, outage_pon_html, caplog
):
    host, state, requests = onu_server
    healthy_pon = state["pon"]
    state["pon"] = outage_pon_html
    caplog.set_level(logging.INFO, logger="custom_components.xpon_onu_stick.api")
    async with aiohttp.ClientSession() as session:
        client = OnuClient(session, host)
        for _ in range(2):
            status = await client.async_get_status()
            assert status.values["tx_power"] is None
            assert status.values["rx_power"] == -40.0
            assert status.values["onu_state"] == "O1"
            assert status.values["bias_current"] == 0.0
            assert status.field_errors == {"tx_power": "Invalid number for tx power: '-inf dBm'"}
        errors = [record for record in caplog.records if record.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "tx power" in errors[0].message
        assert host in errors[0].message
        state["pon"] = healthy_pon
        recovered = await client.async_get_status()
        assert recovered.field_errors == {}
        assert recovered.values["tx_power"] == 1.9399
        assert "Parsing error cleared for tx_power" in caplog.text
        state["pon"] = outage_pon_html
        await client.async_get_status()
        errors = [record for record in caplog.records if record.levelno == logging.ERROR]
        assert len(errors) == 2
    assert (
        requests
        == [
            ("GET", "/status.asp", None),
            ("GET", "/status_pon.asp", None),
        ]
        * 4
    )


@pytest.mark.parametrize("mac", ["not-a-mac", "N/A"])
async def test_invalid_identity_still_rejects_the_snapshot(onu_server, mac):
    host, state, _ = onu_server
    state["device"] = state["device"].replace("020000000001", mac)
    async with aiohttp.ClientSession() as session:
        with pytest.raises(OnuParseError):
            await OnuClient(session, host).async_get_status()


async def test_http_basic_auth(onu_server):
    host, state, requests = onu_server
    state["auth"] = aiohttp.encode_basic_auth("reader", "secret")
    async with aiohttp.ClientSession() as session:
        with pytest.raises(OnuAuthError):
            await OnuClient(session, host).async_get_status()
        assert (await OnuClient(session, host, "reader", "secret").async_get_status()).values[
            "onu_state"
        ] == "O5"
    assert requests[-1][2] == state["auth"]


@pytest.mark.parametrize(
    "code, error",
    [
        (401, OnuAuthError),
        (403, OnuAuthError),
        (302, OnuAuthError),
        (404, OnuConnectionError),
        (500, OnuConnectionError),
    ],
)
async def test_http_errors_and_redirect_not_followed(onu_server, code, error):
    host, state, requests = onu_server
    state["status"] = code
    async with aiohttp.ClientSession() as session:
        with pytest.raises(error):
            await OnuClient(session, host).async_get_status()
    assert [path for _, path, _ in requests] == ["/status.asp"]


async def test_broken_pon_does_not_return_partial_snapshot(onu_server):
    host, state, _ = onu_server
    state["pon"] = "<html>Not found</html>"
    async with aiohttp.ClientSession() as session:
        with pytest.raises(OnuParseError):
            await OnuClient(session, host).async_get_status()


async def test_timeout_mapped_to_connection_error(onu_server):
    host, _, _ = onu_server
    async with aiohttp.ClientSession() as session:
        with patch.object(session, "get", side_effect=asyncio.TimeoutError):
            with pytest.raises(OnuConnectionError):
                await OnuClient(session, host).async_get_status()
