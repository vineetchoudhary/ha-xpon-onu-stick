"""Regression coverage for the observed Realtek form login and session expiry."""

from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType

from custom_components.xpon_onu_stick.api import OnuAuthError, OnuClient, OnuConnectionError
from custom_components.xpon_onu_stick.const import DOMAIN


@pytest.mark.parametrize("protected_response", ["redirect", "html"])
async def test_form_login_uses_actual_fields_and_retains_ip_cookie(onu_server, protected_response):
    host, state, requests = onu_server
    state["form_auth"] = ("reader", "secret")
    state["protected_response"] = protected_response
    # HA's shared session can have no cookie storage. The client must retain
    # IP-address cookies itself, independently of the shared session.
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        client = OnuClient(session, host, "reader", "secret")
        assert (await client.async_get_status()).values["onu_state"] == "O5"
        assert (await client.async_get_status()).values["rx_power"] == -26.382721
    assert state["login_posts"] == [
        {
            "challenge": "",
            "username": "reader",
            "password": "secret",
            "save": "Login",
            "submit-url": "/admin/login.asp",
        }
    ]
    assert [(method, path) for method, path, _ in requests] == [
        ("GET", "/status.asp"),
        ("GET", "/admin/login.asp"),
        ("POST", "/boaform/admin/formLogin"),
        ("GET", "/status.asp"),
        ("GET", "/status_pon.asp"),
        ("GET", "/status.asp"),
        ("GET", "/status_pon.asp"),
    ]


async def test_automatically_renews_expired_session(onu_server):
    host, state, _ = onu_server
    state["form_auth"] = ("reader", "secret")
    async with aiohttp.ClientSession() as session:
        client = OnuClient(session, host, "reader", "secret")
        await client.async_get_status()
        state["sessions"].clear()
        assert (await client.async_get_status()).values["onu_state"] == "O5"
        # A session can expire between the two page requests. Retry the entire
        # snapshot after login so it never combines stale and fresh readings.
        state["expire_before_pon"] = True
        assert len((await client.async_get_status()).values) == 16
    assert len(state["login_posts"]) == 3


@pytest.mark.parametrize("login_status", [200, 302])
async def test_ip_bound_login_without_a_session_cookie(onu_server, login_status):
    host, state, _ = onu_server
    state["form_auth"] = ("reader", "secret")
    state["ip_session"] = True
    state["login_status"] = login_status
    async with aiohttp.ClientSession() as session:
        client = OnuClient(session, host, "reader", "secret")
        assert (await client.async_get_status()).values["onu_state"] == "O5"
        assert not client._cookie_jar.filter_cookies(aiohttp.client.URL(host))
        state["ip_authenticated"] = False
        assert (await client.async_get_status()).values["onu_state"] == "O5"
    assert len(state["login_posts"]) == 2


async def test_wrong_password_has_only_one_login_attempt(onu_server):
    host, state, _ = onu_server
    state["form_auth"] = ("reader", "secret")
    async with aiohttp.ClientSession() as session:
        with pytest.raises(OnuAuthError, match="Login was rejected"):
            await OnuClient(session, host, "reader", "wrong").async_get_status()
    assert len(state["login_posts"]) == 1


async def test_missing_credentials_do_not_submit_login(onu_server):
    host, state, requests = onu_server
    state["form_auth"] = ("reader", "secret")
    async with aiohttp.ClientSession() as session:
        with pytest.raises(OnuAuthError, match="username and password"):
            await OnuClient(session, host).async_get_status()
    assert requests == [("GET", "/status.asp", None)]
    assert not state["login_posts"]


async def test_headerless_login_response_matches_real_firmware(onu_server):
    host, state, _ = onu_server
    state["form_auth"] = ("reader", "secret")
    async with aiohttp.ClientSession() as session:
        original_get = session.get
        calls = 0

        def get(url, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise aiohttp.ClientResponseError(
                    request_info=None,
                    history=(),
                    status=400,
                    message="Bad status line:\n  Expected HTTP/, RTSP/ or ICE/:\n b'<HTML><A HREF=\"/admin/login.asp\">login</A>'",
                )
            return original_get(url, **kwargs)

        with patch.object(session, "get", side_effect=get):
            status = await OnuClient(session, host, "reader", "secret").async_get_status()
    assert status.values["onu_state"] == "O5"
    assert len(state["login_posts"]) == 1


async def test_unrelated_malformed_http_is_not_treated_as_login(onu_server):
    host, state, _ = onu_server
    async with aiohttp.ClientSession() as session:
        with patch.object(
            session,
            "get",
            side_effect=aiohttp.ClientResponseError(
                request_info=None, history=(), status=400, message="Bad status line: Expected HTTP/"
            ),
        ):
            with pytest.raises(OnuConnectionError):
                await OnuClient(session, host, "reader", "secret").async_get_status()
    assert not state["login_posts"]


@pytest.mark.parametrize(
    "change",
    [
        lambda html: html.replace("/boaform/admin/formLogin", "/boaform/admin/formStatus"),
        lambda html: html.replace('name="challenge"', 'name="challenge" value="unsupported-hash"'),
    ],
)
async def test_unsupported_login_form_does_not_post(onu_server, change):
    host, state, requests = onu_server
    state["form_auth"] = ("reader", "secret")
    state["login_html"] = change(state["login_html"])
    async with aiohttp.ClientSession() as session:
        with pytest.raises(OnuAuthError, match="unsupported login form"):
            await OnuClient(session, host, "reader", "secret").async_get_status()
    assert not state["login_posts"]
    assert all(method == "GET" for method, _, _ in requests)


async def test_hidden_fields_and_login_page_cookie_preserved(onu_server):
    host, state, _ = onu_server
    state["form_auth"] = ("reader", "secret")
    state["csrf"] = True
    state["login_html"] = state["login_html"].replace(
        '<input type="hidden" name="challenge">',
        '<input type="hidden" name="challenge"><input type="hidden" name="csrf_token" value="seed">',
    )
    async with aiohttp.ClientSession() as session:
        assert (
            len((await OnuClient(session, host, "reader", "secret").async_get_status()).values)
            == 16
        )
    assert state["login_posts"][0]["csrf_token"] == "seed"


@pytest.mark.parametrize(
    "location", ["/reboot.asp", "http://example.com/", "http://user:pass@127.0.0.1/"]
)
async def test_login_redirect_never_requests_settings_or_other_hosts(onu_server, location):
    host, state, requests = onu_server
    state["form_auth"] = ("reader", "secret")
    state["login_redirect"] = location
    async with aiohttp.ClientSession() as session:
        with pytest.raises(OnuAuthError, match="unsupported redirect"):
            await OnuClient(session, host, "reader", "secret").async_get_status()
    assert requests[-1][1] == "/boaform/admin/formLogin"


async def test_form_login_in_home_assistant_and_expiry_without_reauth_prompt(hass, onu_server):
    host, state, _ = onu_server
    state["form_auth"] = ("reader", "secret")
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={
            CONF_HOST: host,
            CONF_USERNAME: "reader",
            CONF_PASSWORD: "secret",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    assert len(hass.states.async_all("sensor")) == 22
    state["sessions"].clear()
    await entry.runtime_data.async_refresh()
    assert hass.states.get("sensor.aot5222zy_onu_state").state == "O5"
    assert not hass.config_entries.flow.async_progress()


async def test_form_reauthentication_after_password_change(hass, onu_server):
    host, state, _ = onu_server
    state["form_auth"] = ("reader", "secret")
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={
            CONF_HOST: host,
            CONF_USERNAME: "reader",
            CONF_PASSWORD: "secret",
        },
    )
    entry = result["result"]
    await hass.async_block_till_done()
    state["form_auth"] = ("reader", "new-secret")
    state["sessions"].clear()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    flow = next(
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == "reauth"
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            CONF_USERNAME: "reader",
            CONF_PASSWORD: "new-secret",
        },
    )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert hass.states.get("sensor.aot5222zy_onu_state").state == "O5"
