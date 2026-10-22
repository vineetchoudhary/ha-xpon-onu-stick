"""Verify the captured logout transaction and its non-critical failure behavior."""

import asyncio
from unittest.mock import patch

import aiohttp
import pytest

from custom_components.xpon_onu_stick.api import OnuClient, OnuError

LOGOUT_PATH = "/boaform/admin/formLogout"
POLL_REQUESTS = [
    ("GET", "/status.asp", None),
    ("GET", "/status_pon.asp", None),
    ("POST", LOGOUT_PATH, None),
]


@pytest.mark.parametrize("options", [{}, {"logout_after_poll": False}])
@pytest.mark.parametrize("auth", ["none", "basic", "cookie", "ip"])
async def test_disabled_logout_preserves_sessions(onu_server, options, auth):
    host, state, requests = onu_server
    credentials = ("", "") if auth == "none" else ("reader", "secret")
    if auth in {"cookie", "ip"}:
        state["form_auth"] = credentials
        state["ip_session"] = auth == "ip"
    elif auth == "basic":
        state["auth"] = aiohttp.encode_basic_auth(*credentials)
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        client = OnuClient(session, host, *credentials, **options)
        for _ in range(2):
            assert (await client.async_get_status()).values["onu_state"] == "O5"
    assert not state["logout_posts"]
    assert not any(path == LOGOUT_PATH for _, path, _ in requests)
    assert len(state["login_posts"]) == (1 if auth in {"cookie", "ip"} else 0)
    if auth == "cookie":
        assert state["sessions"] == {"session-1"}
    elif auth == "ip":
        assert state["ip_authenticated"]


async def test_default_poll_does_not_close_another_clients_ip_session(onu_server):
    host, state, requests = onu_server
    state.update(form_auth=("reader", "secret"), ip_session=True, ip_authenticated=True)
    async with aiohttp.ClientSession() as session:
        client = OnuClient(session, host)
        await client.async_get_status()
        await client.async_get_status()
    assert requests == POLL_REQUESTS[:2] * 2
    assert state["ip_authenticated"]
    assert not state["login_posts"]
    assert not state["logout_posts"]


@pytest.mark.parametrize("mode", ["gpon", "epon"])
@pytest.mark.parametrize("auth", ["none", "basic", "cookie", "ip"])
async def test_only_owned_form_sessions_are_logged_out(
    onu_server, epon_device_html, epon_pon_html, mode, auth
):
    host, state, requests = onu_server
    if mode == "epon":
        state.update(device=epon_device_html, pon=epon_pon_html)
    credentials = ("", "") if auth == "none" else ("reader", "secret")
    if auth in {"cookie", "ip"}:
        state["form_auth"] = credentials
        state["ip_session"] = auth == "ip"
    elif auth == "basic":
        state["auth"] = aiohttp.encode_basic_auth(*credentials)
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        client = OnuClient(session, host, *credentials, logout_after_poll=True)
        for _ in range(2):
            result = await client.async_get_status()
            assert result.pon_mode == mode
            assert requests[-1][0:2] == (
                ("POST", LOGOUT_PATH) if auth in {"cookie", "ip"} else ("GET", "/status_pon.asp")
            )
            assert not state["sessions"]
            assert not state["ip_authenticated"]
            assert not client._cookie_jar.filter_cookies(aiohttp.client.URL(host))
    assert len(state["logout_posts"]) == (2 if auth in {"cookie", "ip"} else 0)
    assert len(state["login_posts"]) == (2 if auth in {"cookie", "ip"} else 0)
    for index, logout in enumerate(state["logout_posts"], start=1):
        assert logout["data"] == {"save": "Logout", "submit-url": "/admin/logout.asp"}
        assert logout["referer"] == f"{host}/admin/logout.asp"
        assert logout["session"] == (f"session-{index}" if auth == "cookie" else None)
    if auth == "none":
        assert requests == POLL_REQUESTS[:2] * 2


async def test_enabled_logout_preserves_an_existing_ip_session_without_a_login(onu_server):
    host, state, requests = onu_server
    state.update(form_auth=("reader", "secret"), ip_session=True, ip_authenticated=True)
    async with aiohttp.ClientSession() as session:
        await OnuClient(session, host, logout_after_poll=True).async_get_status()
    assert requests == POLL_REQUESTS[:2]
    assert state["ip_authenticated"]
    assert not state["login_posts"]
    assert not state["logout_posts"]


@pytest.mark.parametrize("status", [401, 403, 404, 500, 302])
async def test_logout_http_failure_keeps_readings_and_retries_next_poll(onu_server, caplog, status):
    host, state, requests = onu_server
    state.update(form_auth=("reader", "secret"), logout_status=status)
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        client = OnuClient(session, host, "reader", "secret", logout_after_poll=True)
        result = await client.async_get_status()
        assert result.values["onu_state"] == "O5"
        assert result.values["rx_power"] == -26.382721
        assert len(state["login_posts"]) == 1
        assert len(state["logout_posts"]) == 1
        assert state["sessions"] == {"session-1"}
        assert client._cookie_jar.filter_cookies(aiohttp.client.URL(host))
        assert requests[-1][1] == LOGOUT_PATH
        assert "Unable to confirm ONU logout" in caplog.text
        state["logout_status"] = 200
        await client.async_get_status()
        assert len(state["login_posts"]) == 1
        assert len(state["logout_posts"]) == 2
        assert not state["sessions"]
        assert not client._cookie_jar.filter_cookies(aiohttp.client.URL(host))


@pytest.mark.parametrize(
    "body",
    [
        "",
        "<h4>ERROR: logout failed!</h4>",
        '<input type="password">',
        "<!-- <h4>OK: logout successfully!</h4> -->",
        '<script>var result="<h4>OK: logout successfully!</h4>";</script>',
        "<h4>Not OK: logout successfully!</h4>",
    ],
)
async def test_http_200_alone_does_not_confirm_logout(onu_server, caplog, body):
    host, state, requests = onu_server
    state["logout_html"] = body
    state["form_auth"] = ("reader", "secret")
    async with aiohttp.ClientSession() as session:
        result = await OnuClient(
            session, host, "reader", "secret", logout_after_poll=True
        ).async_get_status()
    assert result.values["onu_state"] == "O5"
    assert requests[-1][0:2] == ("POST", LOGOUT_PATH)
    assert len(state["logout_posts"]) == 1
    assert "Unable to confirm ONU logout" in caplog.text


async def test_logout_timeout_keeps_the_successful_snapshot(onu_server, caplog):
    host, state, requests = onu_server
    state["form_auth"] = ("reader", "secret")
    async with aiohttp.ClientSession() as session:
        client = OnuClient(session, host, "reader", "secret", logout_after_poll=True)
        await client.async_get_status(logout_after_poll=False)
        requests.clear()
        with patch.object(session, "post", side_effect=TimeoutError):
            result = await client.async_get_status()
    assert result.values["onu_state"] == "O5"
    assert [(method, path) for method, path, _ in requests] == [
        ("GET", "/status.asp"),
        ("GET", "/status_pon.asp"),
    ]
    assert "Unable to confirm ONU logout" in caplog.text


@pytest.mark.parametrize("failure", ["device", "pon", "http", "identity"])
async def test_failed_status_read_does_not_issue_logout(onu_server, failure):
    host, state, requests = onu_server
    if failure in {"device", "pon"}:
        state[failure] = "<html>Missing status</html>"
    elif failure == "http":
        state["status"] = 500
    else:
        state["device"] = state["device"].replace("020000000001", "invalid-mac")
    async with aiohttp.ClientSession() as session:
        with pytest.raises(OnuError):
            await OnuClient(session, host, logout_after_poll=True).async_get_status()
    assert not state["logout_posts"]
    assert all(method == "GET" for method, _, _ in requests)


async def test_poll_lock_includes_logout(onu_server):
    host, state, requests = onu_server
    state["form_auth"] = ("reader", "secret")
    logout_started = asyncio.Event()
    allow_logout = asyncio.Event()
    async with aiohttp.ClientSession() as session:
        client = OnuClient(session, host, "reader", "secret", logout_after_poll=True)
        await client.async_get_status(logout_after_poll=False)
        requests.clear()
        original_logout = client._async_logout

        async def delayed_logout():
            logout_started.set()
            await allow_logout.wait()
            await original_logout()

        with patch.object(client, "_async_logout", side_effect=delayed_logout):
            first = asyncio.create_task(client.async_get_status())
            second = None
            try:
                async with asyncio.timeout(5):
                    await logout_started.wait()
                    second = asyncio.create_task(client.async_get_status())
                    await asyncio.sleep(0)
                    assert [(method, path) for method, path, _ in requests] == [
                        ("GET", "/status.asp"),
                        ("GET", "/status_pon.asp"),
                    ]
                    assert not first.done()
                    assert not second.done()
                    allow_logout.set()
                    await asyncio.gather(first, second)
            finally:
                allow_logout.set()
                for task in (first, second):
                    if task is not None and not task.done():
                        task.cancel()
                await asyncio.gather(
                    *(task for task in (first, second) if task), return_exceptions=True
                )
    assert len(state["logout_posts"]) == 2
    assert requests[-1][0:2] == ("POST", LOGOUT_PATH)
