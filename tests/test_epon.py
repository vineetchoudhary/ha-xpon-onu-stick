"""Verify mode detection using captured EPON HTML and malformed-page boundaries."""

import re

import aiohttp
import pytest

from custom_components.xpon_onu_stick.api import (
    OnuAuthError,
    OnuClient,
    OnuParseError,
    parse_pon_status_page,
)


def replace_llid_table(html, contents):
    """Keep the captured optical measurements while varying only the LLID table."""
    return re.sub(
        r"<table width=400 border=0>\s*<td[^>]*>.*?EPON LLID Status.*?</table>",
        lambda _: contents,
        html,
        count=1,
        flags=re.DOTALL,
    )


def llid_table(rows):
    return (
        '<table><tr><td colspan="2">EPON LLID Status</td></tr>'
        "<tr><th>index</th><th>Status</th></tr>"
        + "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
        + "</table>"
    )


def test_captured_epon_pon_page(epon_pon_html):
    mode, values = parse_pon_status_page(epon_pon_html)
    assert mode == "epon"
    assert values == {
        "temperature": 41.0,
        "voltage": 3.32,
        "tx_power": 2.3,
        "rx_power": -18.1,
        "bias_current": 16.8,
        "epon_llid_0_status": 1,
        "epon_llid_1_status": 0,
    }


def test_gpon_autodetection_preserves_original_readings(pon_html):
    mode, values = parse_pon_status_page(pon_html)
    assert mode == "gpon"
    assert len(values) == 8
    assert values["onu_state"] == "O5"
    assert values["onu_id"] == 0
    assert values["loid_status"] == "Initial Status"
    assert values["rx_power"] == -26.382721


@pytest.mark.parametrize(
    "label, key",
    [
        ("ONU State", "onu_state"),
        ("ONU ID", "onu_id"),
        ("LOID Status", "loid_status"),
        ("Rx Power", "rx_power"),
    ],
)
def test_damaged_gpon_is_not_misidentified_as_epon(pon_html, label, key):
    errors = {}
    mode, values = parse_pon_status_page(pon_html.replace(label, "Missing"), field_errors=errors)
    assert mode == "gpon"
    assert values[key] is None
    assert set(errors) == {key}
    assert values["temperature"] == 37.277344


@pytest.mark.parametrize("raw", ["", "-", "--", "N/A", "unknown"])
def test_unknown_epon_values_are_not_zero(epon_pon_html, raw):
    html = replace_llid_table(epon_pon_html, llid_table([(0, raw), (1, 0)]))
    html = html.replace("-18.1  dBm", raw)
    mode, values = parse_pon_status_page(html)
    assert mode == "epon"
    assert values["rx_power"] is None
    assert values["epon_llid_0_status"] is None
    assert values["epon_llid_1_status"] == 0


def test_llid_indices_are_not_row_positions_or_limited_to_two(epon_pon_html):
    html = replace_llid_table(epon_pon_html, llid_table([(7, 0), (3, 42), (0, 1)]))
    _, values = parse_pon_status_page(html)
    assert values["epon_llid_7_status"] == 0
    assert values["epon_llid_3_status"] == 42
    assert values["epon_llid_0_status"] == 1
    assert "epon_llid_1_status" not in values


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [(0, 1), (0, 0)],
        [(0, 1), ("00", 0)],
        [("-1", 1)],
        [("bad", 1)],
        [("0.5", 1)],
        [(0, 1, "extra")],
        [(0,)],
    ],
)
def test_invalid_llid_tables_fail(epon_pon_html, rows):
    with pytest.raises(OnuParseError):
        parse_pon_status_page(replace_llid_table(epon_pon_html, llid_table(rows)))


@pytest.mark.parametrize("raw", ["bad", "1.5", "-1", "NaN"])
def test_invalid_llid_status_only_affects_that_index(epon_pon_html, raw):
    errors = {}
    html = replace_llid_table(epon_pon_html, llid_table([(0, raw), (1, 0)]))
    mode, values = parse_pon_status_page(html, field_errors=errors)
    assert mode == "epon"
    assert values["epon_llid_0_status"] is None
    assert values["epon_llid_1_status"] == 0
    assert values["rx_power"] == -18.1
    assert set(errors) == {"epon_llid_0_status"}


def test_oversized_llid_index_raises_parse_error(epon_pon_html, oversized_integer):
    html = replace_llid_table(epon_pon_html, llid_table([(oversized_integer, 1)]))
    with pytest.raises(OnuParseError, match="Invalid EPON LLID index"):
        parse_pon_status_page(html)


def test_oversized_llid_status_is_isolated(epon_pon_html, oversized_integer):
    html = replace_llid_table(epon_pon_html, llid_table([(0, oversized_integer), (1, 0)]))
    errors = {}
    mode, values = parse_pon_status_page(html, field_errors=errors)
    assert mode == "epon"
    assert values["epon_llid_0_status"] is None
    assert values["epon_llid_1_status"] == 0
    assert values["rx_power"] == -18.1
    assert set(errors) == {"epon_llid_0_status"}
    assert "Invalid EPON LLID status" in errors["epon_llid_0_status"]
    assert parse_pon_status_page(html)[1] == values  # Also safe without diagnostics.


@pytest.mark.parametrize(
    "table",
    [
        "",
        "<!-- " + llid_table([(0, 1)]) + " -->",
        "<script>" + llid_table([(0, 1)]) + "</script>",
        llid_table([(0, 1)]).replace("EPON LLID Status", "Unrelated Status"),
        llid_table([(0, 1)]).replace("index", "unknown"),
        llid_table([(0, 1)]) * 2,
    ],
)
def test_epon_requires_one_explicit_valid_table(epon_pon_html, table):
    with pytest.raises(OnuParseError):
        parse_pon_status_page(replace_llid_table(epon_pon_html, table))


def test_unrelated_table_rows_do_not_override_llids(epon_pon_html):
    _, values = parse_pon_status_page(
        epon_pon_html + "<table><tr><td>0</td><td>99</td></tr></table>"
    )
    assert values["epon_llid_0_status"] == 1


def test_ambiguous_modes_rejected(pon_html):
    with pytest.raises(OnuParseError, match="Ambiguous"):
        parse_pon_status_page(pon_html + llid_table([(0, 1)]))
    # Comments and scripts cannot switch a GPON page to EPON.
    mode, _ = parse_pon_status_page(pon_html + "<!--" + llid_table([(0, 1)]) + "-->")
    assert mode == "gpon"


@pytest.mark.parametrize("replacement", ["missing", "NAN", "2 V"])
def test_invalid_epon_optical_value_is_isolated(epon_pon_html, replacement):
    errors = {}
    mode, values = parse_pon_status_page(
        epon_pon_html.replace("-18.1  dBm", replacement), field_errors=errors
    )
    assert mode == "epon"
    assert values["rx_power"] is None
    assert values["epon_llid_0_status"] == 1
    assert set(errors) == {"rx_power"}


def test_missing_epon_optical_field_is_isolated(epon_pon_html):
    errors = {}
    mode, values = parse_pon_status_page(
        epon_pon_html.replace("Temperature", "Missing"), field_errors=errors
    )
    assert mode == "epon"
    assert values["temperature"] is None
    assert values["rx_power"] == -18.1
    assert values["epon_llid_0_status"] == 1
    assert set(errors) == {"temperature"}


def test_pon_login_page_still_requires_authentication(login_html):
    with pytest.raises(OnuAuthError):
        parse_pon_status_page(login_html)


async def test_client_reads_captured_epon_pages(onu_server, epon_device_html, epon_pon_html):
    host, state, requests = onu_server
    state.update(device=epon_device_html, pon=epon_pon_html)
    async with aiohttp.ClientSession() as session:
        status = await OnuClient(session, host).async_get_status()
    assert status.pon_mode == "epon"
    assert status.mac_address == "02:00:00:00:00:01"
    assert status.name == "XPON ONU 02:00:00:00:00:01"
    assert status.values["device_name"] is None  # Never read commented-out PON Bridge.
    assert status.values["firmware_version"] == "V2.11.00P3T1"
    assert status.values["uptime"] == "19 days, 13:01"
    assert status.values["cpu_usage"] == 1
    assert status.values["memory_usage"] == 30
    assert status.values["ip_address"] == "192.0.2.1"
    assert status.values["epon_llid_0_status"] == 1
    assert status.values["epon_llid_1_status"] == 0
    assert "onu_state" not in status.values
    assert requests == [
        ("GET", "/status.asp", None),
        ("GET", "/status_pon.asp", None),
    ]


async def test_epon_retains_reported_device_name(onu_server, epon_pon_html):
    host, state, _ = onu_server
    state["pon"] = epon_pon_html
    async with aiohttp.ClientSession() as session:
        status = await OnuClient(session, host).async_get_status()
    assert status.name == "AOT5222ZY"
    assert status.values["device_name"] == "AOT5222ZY"


@pytest.mark.parametrize("auth_type", ["basic", "form"])
async def test_epon_authentication_and_session_expiry(
    onu_server, epon_device_html, epon_pon_html, auth_type
):
    host, state, requests = onu_server
    state.update(device=epon_device_html, pon=epon_pon_html)
    if auth_type == "basic":
        state["auth"] = aiohttp.encode_basic_auth("reader", "secret")
    else:
        state["form_auth"] = ("reader", "secret")
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        client = OnuClient(session, host, "reader", "secret", logout_after_poll=True)
        assert (await client.async_get_status()).pon_mode == "epon"
        if auth_type == "form":
            await client._async_login()
            state["expire_before_pon"] = True
        status = await client.async_get_status()
    assert status.values["epon_llid_0_status"] == 1
    assert len(state["login_posts"]) == (3 if auth_type == "form" else 0)
    assert len(state["logout_posts"]) == 2
    assert not state["sessions"]
    assert all(
        (method == "GET" and path in {"/status.asp", "/status_pon.asp", "/admin/login.asp"})
        or (method == "POST" and path in {"/boaform/admin/formLogin", "/boaform/admin/formLogout"})
        for method, path, _ in requests
    )


async def test_missing_gpon_device_name_uses_upstream_fallback(onu_server, epon_device_html):
    host, state, _ = onu_server
    state["device"] = epon_device_html
    async with aiohttp.ClientSession() as session:
        status = await OnuClient(session, host).async_get_status()
    assert status.name == "XPON ONU Stick (02:00:00:00:00:01)"
    assert set(status.field_errors) == {"device_name"}


async def test_missing_epon_identity_fails(onu_server, epon_device_html, epon_pon_html):
    host, state, _ = onu_server
    state.update(device=epon_device_html.replace("MAC Address", "Missing"), pon=epon_pon_html)
    async with aiohttp.ClientSession() as session:
        with pytest.raises(OnuParseError):
            await OnuClient(session, host).async_get_status()


@pytest.mark.parametrize(
    "label, key", [("Firmware Version", "firmware_version"), ("CPU Usage", "cpu_usage")]
)
async def test_missing_epon_device_field_is_isolated(
    onu_server, epon_device_html, epon_pon_html, label, key
):
    host, state, _ = onu_server
    state.update(device=epon_device_html.replace(label, "Missing"), pon=epon_pon_html)
    async with aiohttp.ClientSession() as session:
        status = await OnuClient(session, host).async_get_status()
    assert status.values[key] is None
    assert status.values["rx_power"] == -18.1
    assert set(status.field_errors) == {key}
    assert not state["logout_posts"]
