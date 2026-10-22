"""Replay both supplied devices and protect authentication and parser boundaries."""

import asyncio
import sys
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

from custom_components.xpon_onu_stick.api import (
    DEVICE_FIELDS,
    OnuAuthError,
    OnuClient,
    OnuConnectionError,
    OnuParseError,
    OnuSessionBusy,
    _FormResultParser,
    parse_pon_status_page,
    parse_status_page,
)
from custom_components.xpon_onu_stick.client import async_get_onu_client
from custom_components.xpon_onu_stick.const import CONF_LOGOUT_AFTER_POLL, DOMAIN


@pytest.fixture(
    params=["gpon", "epon"],
    ids=["odi-dfp-34x-2c2-V1.0-220923", "bdcom-unknown-model-V2.11.00P3T1"],
)
def saved_device(request, gpon_fixture_dir, epon_fixture_dir):
    mode = request.param
    directory = gpon_fixture_dir if mode == "gpon" else epon_fixture_dir
    return {
        "mode": mode,
        "device": (directory / "device_status.html").read_text(),
        "pon": (directory / "pon_status.html").read_text(),
        "login": (directory / "login.html").read_text(),
        "logout": (directory / "logout_success.html").read_text(),
    }


def test_saved_status_pages(saved_device):
    errors = {}
    device = parse_status_page(saved_device["device"], DEVICE_FIELDS, field_errors=errors)
    mode, values = parse_pon_status_page(saved_device["pon"], field_errors=errors)
    assert mode == saved_device["mode"]
    assert device["mac_address"] == "020000000001"
    if mode == "gpon":
        assert device["firmware_version"] == "V1.0-220923"
        assert device["uptime"] == "2 days, 19:12"
        assert values["temperature"] == 36.9375
        assert values["rx_power"] == -26.575773
        assert values["onu_state"] == "O5"
        assert errors == {}
    else:
        assert device["firmware_version"] == "V2.11.00P3T1"
        assert device["device_name"] is None
        assert values["epon_llid_0_status"] == 1
        assert values["epon_llid_1_status"] == 0
        assert values["rx_power"] == -18.1
        assert "onu_state" not in values
        assert set(errors) == {"device_name"}


async def test_saved_pages_load_and_poll_without_duplicate_login(hass, onu_server, saved_device):
    host, state, _ = onu_server
    state.update(
        device=saved_device["device"],
        pon=saved_device["pon"],
        login_html=saved_device["login"].replace("http://192.0.2.2", host),
        form_auth=("reader", "secret"),
        ip_session=saved_device["mode"] == "epon",
        single_session=True,
        logout_html=saved_device["logout"],
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={CONF_HOST: host, CONF_USERNAME: "reader", CONF_PASSWORD: "secret"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED
    assert len(hass.states.async_all("sensor")) == (22 if saved_device["mode"] == "gpon" else 20)
    client = entry.runtime_data.client
    assert client is async_get_onu_client(hass, host, "reader", "secret")
    await entry.runtime_data.async_refresh()
    assert len(state["login_posts"]) == 1  # Validation and polling share our session.
    assert not state["logout_posts"]

    options = await hass.config_entries.options.async_init(entry.entry_id)
    options = await hass.config_entries.options.async_configure(
        options["flow_id"], {"next_step_id": "session"}
    )
    await hass.config_entries.options.async_configure(
        options["flow_id"], {CONF_LOGOUT_AFTER_POLL: True}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.client is client
    assert len(state["logout_posts"]) == 1
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.last_update_success
    assert len(state["login_posts"]) == 2
    assert len(state["logout_posts"]) == 2
    assert not state["sessions"] and not state["ip_authenticated"]
    await hass.config_entries.async_remove(entry.entry_id)
    assert async_get_onu_client(hass, host, "reader", "secret") is not client


async def test_busy_login_does_not_close_an_existing_session(onu_server):
    host, state, _ = onu_server
    state.update(form_auth=("reader", "secret"), single_session=True, sessions={"browser"})
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        client = OnuClient(session, host, "reader", "secret", logout_after_poll=True)
        with pytest.raises(OnuSessionBusy, match="active management session"):
            await client.async_get_status()
    assert state["sessions"] == {"browser"}
    assert len(state["login_posts"]) == 1
    assert not state["logout_posts"]


async def test_failed_reconfigure_keeps_the_working_authenticated_client(hass, onu_server):
    host, state, _ = onu_server
    state.update(form_auth=("reader", "secret"), single_session=True)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={CONF_HOST: host, CONF_USERNAME: "reader", CONF_PASSWORD: "secret"},
    )
    await hass.async_block_till_done()
    entry = result["result"]
    client = entry.runtime_data.client
    failed = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
        data={CONF_HOST: host, CONF_USERNAME: "reader", CONF_PASSWORD: "wrong"},
    )
    assert failed["type"] is FlowResultType.FORM
    assert failed["errors"] == {"base": "session_busy"}
    assert async_get_onu_client(hass, host, "reader", "secret") is client
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.last_update_success
    assert not state["logout_posts"]


async def test_active_browser_session_does_not_start_password_reauthentication(hass, onu_server):
    host, state, _ = onu_server
    state.update(form_auth=("reader", "secret"), single_session=True)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={CONF_HOST: host, CONF_USERNAME: "reader", CONF_PASSWORD: "secret"},
    )
    await hass.async_block_till_done()
    entry = result["result"]
    state["sessions"] = {"browser"}
    await entry.runtime_data.async_refresh()
    assert not entry.runtime_data.last_update_success
    assert not hass.config_entries.flow.async_progress()
    assert state["sessions"] == {"browser"}
    state["sessions"].clear()
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.last_update_success
    assert not hass.config_entries.flow.async_progress()


async def test_hostname_cookies_do_not_enter_home_assistants_shared_session(hass, onu_server):
    host, state, _ = onu_server
    host = host.replace("127.0.0.1", "localhost")
    state["form_auth"] = ("reader", "secret")
    client = async_get_onu_client(hass, host, "reader", "secret")
    await client.async_get_status()
    shared_session = async_get_clientsession(hass)
    assert client._session is not shared_session
    assert isinstance(client._session.cookie_jar, aiohttp.DummyCookieJar)
    assert not shared_session.cookie_jar.filter_cookies(URL(host))
    assert client._cookie_jar.filter_cookies(URL(host))


@pytest.mark.parametrize("enabled", [False, True])
async def test_borrowed_ip_session_is_preserved(onu_server, enabled):
    host, state, _ = onu_server
    state.update(form_auth=("reader", "secret"), ip_session=True, ip_authenticated=True)
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        client = OnuClient(session, host, logout_after_poll=enabled)
        for _ in range(2):
            assert (await client.async_get_status()).values["onu_state"] == "O5"
    assert state["ip_authenticated"]
    assert not state["login_posts"] and not state["logout_posts"]


async def test_poll_and_validation_share_device_lock(onu_server):
    host, state, requests = onu_server
    state.update(form_auth=("reader", "secret"), ip_session=True, single_session=True)
    read_finished = asyncio.Event()
    release_poll = asyncio.Event()
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        polling = OnuClient(session, host, "reader", "secret", logout_after_poll=True)
        validation = OnuClient(session, host + "/", "reader", "secret")
        assert polling._lock is validation._lock
        original = polling._async_read_status

        async def delayed_read():
            result = await original()
            read_finished.set()
            await release_poll.wait()
            return result

        with patch.object(polling, "_async_read_status", side_effect=delayed_read):
            first = asyncio.create_task(polling.async_get_status())
            second = None
            try:
                async with asyncio.timeout(5):
                    await read_finished.wait()
                    before = len(requests)
                    second = asyncio.create_task(validation.async_get_status())
                    await asyncio.sleep(0)
                    assert not second.done() and len(requests) == before
                    release_poll.set()
                    results = await asyncio.gather(first, second)
                    assert all(result.values["onu_state"] == "O5" for result in results)
            finally:
                release_poll.set()
                for task in (first, second):
                    if task is not None and not task.done():
                        task.cancel()
                await asyncio.gather(
                    *(task for task in (first, second) if task), return_exceptions=True
                )
    assert len(state["logout_posts"]) == 1
    assert len(state["login_posts"]) == 2
    assert state["ip_authenticated"]  # Validation never logs out.


@pytest.mark.parametrize(
    "action",
    [
        "http://other.example/boaform/admin/formLogin",
        "//other.example/boaform/admin/formLogin",
        "/boaform/admin/formLogin?next=settings",
        "/boaform/admin/formLogin#fragment",
        "http://user:secret@other.example/boaform/admin/formLogin",
        "/boaform/admin/formStatus",
    ],
)
async def test_untrusted_login_action_never_receives_credentials(onu_server, action):
    host, state, requests = onu_server
    state.update(
        form_auth=("reader", "secret"),
        login_html=state["login_html"].replace(
            "action=/boaform/admin/formLogin", f'action="{action}"'
        ),
    )
    async with aiohttp.ClientSession() as session:
        with pytest.raises(OnuAuthError, match="unsupported login form"):
            await OnuClient(session, host, "reader", "secret").async_get_status()
    assert not state["login_posts"]
    assert all(method == "GET" for method, _, _ in requests)


@pytest.mark.parametrize("page", ["device", "pon"])
async def test_large_pages_are_rejected_before_sensor_creation(onu_server, page):
    host, state, _ = onu_server
    state[page] += " " * (256 * 1024)
    async with aiohttp.ClientSession() as session:
        with pytest.raises(OnuParseError, match="page size"):
            await OnuClient(session, host).async_get_status()
    assert not state["logout_posts"]


async def test_only_status_and_authentication_endpoints_are_allowed(onu_server):
    host, _, requests = onu_server
    async with aiohttp.ClientSession() as session:
        client = OnuClient(session, host)
        with pytest.raises(OnuConnectionError, match="Unsupported ONU request"):
            await client._request("POST", "/boaform/admin/formStatus", {"save": "Apply"})
    assert requests == []


@pytest.mark.parametrize("field", ["index", "status"])
def test_llid_text_is_bounded_even_with_python_limit_disabled(epon_pon_html, field):
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(0)
    try:
        raw = "9" * 5000
        if field == "index":
            html = epon_pon_html.replace("<b>0</b>", f"<b>{raw}</b>", 1)
            with pytest.raises(OnuParseError, match="LLID index"):
                parse_pon_status_page(html)
        else:
            html = epon_pon_html.replace(
                "<b>1</b></font></td><br>", f"<b>{raw}</b></font></td><br>", 1
            )
            errors = {}
            _, values = parse_pon_status_page(html, field_errors=errors)
            assert values["epon_llid_0_status"] is None
            assert values["epon_llid_1_status"] == 0
            assert values["rx_power"] == -18.1
            assert len(errors["epon_llid_0_status"]) < 160
    finally:
        sys.set_int_max_str_digits(previous)


@pytest.mark.parametrize("field", ["index", "status"])
async def test_corrupt_initial_llid_does_not_report_an_invalid_address(
    hass, onu_server, epon_pon_html, field
):
    host, state, _ = onu_server
    if field == "index":
        state["pon"] = epon_pon_html.replace("<b>0</b>", f"<b>{'9' * 5000}</b>", 1)
    else:
        state["pon"] = epon_pon_html.replace(
            "<b>1</b></font></td><br>", f"<b>{'9' * 5000}</b></font></td><br>", 1
        )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={CONF_HOST: host}
    )
    if field == "index":
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "unsupported_device"}
    else:
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        entry = result["result"]
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.data.values["epon_llid_0_status"] is None
        assert entry.runtime_data.data.values["rx_power"] == -18.1


def test_saved_busy_result_cannot_be_forged_in_comments_or_scripts(epon_fixture_dir):
    html = (epon_fixture_dir / "login_busy.html").read_text()
    parser = _FormResultParser()
    parser.feed(html)
    assert parser.session_busy and not parser.logout_success
    for wrapped in (f"<!--{html}-->", f"<script>{html}</script>"):
        parser = _FormResultParser()
        parser.feed(wrapped)
        assert not parser.session_busy and not parser.logout_success


async def test_changing_llid_indices_cannot_grow_the_registry_without_limit(
    hass, onu_server, epon_pon_html
):
    host, state, _ = onu_server
    state["pon"] = epon_pon_html
    with patch("custom_components.xpon_onu_stick.sensor.MAX_EPON_LLID_SENSORS", 2):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data={CONF_HOST: host}
        )
        await hass.async_block_till_done()
        entry = result["result"]
        state["pon"] = epon_pon_html.replace("<b>1</b></font></td>\n", "<b>3</b></font></td>\n")
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert entry.runtime_data.last_update_success
        assert len(hass.states.async_all("sensor")) == 20
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        assert len([entity for entity in entities if "_epon_llid_" in entity.unique_id]) == 2
        state["pon"] = epon_pon_html
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert len(hass.states.async_all("sensor")) == 20
