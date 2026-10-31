"""Interface/profile boundaries and normalized capabilities for captured firmware."""

from dataclasses import replace
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType

from custom_components.xpon_onu_stick.api import OnuClient
from custom_components.xpon_onu_stick.const import DEVICE_STATUS_PATH, PON_STATUS_PATH
from custom_components.xpon_onu_stick.devices.boa import BoaAdapter, profiles
from custom_components.xpon_onu_stick.devices.boa.profiles import BoaProfile
from custom_components.xpon_onu_stick.models import (
    HttpPolicy,
    OnuCapabilities,
    OnuConnectionError,
    OnuParseError,
    OnuStatus,
)
from custom_components.xpon_onu_stick.transport import OnuTransport


async def read_pages(device: str, pon: str) -> OnuStatus:
    """Replay actual page bodies without network access or Home Assistant objects."""
    pages = {DEVICE_STATUS_PATH: device, PON_STATUS_PATH: pon}

    async def request(method, path, data=None):
        assert method == "GET" and data is None
        return pages[path]

    return await BoaAdapter().async_read_status(request)


@pytest.mark.parametrize(
    "fixture_dir, mode, profile_id, rx, fields",
    [
        ("gpon_fixture_dir", "gpon", "boa", -26.575773, 16),
        ("epon_fixture_dir", "epon", "boa-epon-v2.11.00p3t1", -18.1, 15),
    ],
)
async def test_captures_share_an_adapter_and_keep_normalized_readings(
    request, fixture_dir, mode, profile_id, rx, fields
):
    directory = request.getfixturevalue(fixture_dir)
    status = await read_pages(
        (directory / "device_status.html").read_text(),
        (directory / "pon_status.html").read_text(),
    )
    assert status.mac_address == "02:00:00:00:00:01"
    assert status.profile_id == profile_id
    assert status.pon_mode == mode
    assert status.values["rx_power"] == rx
    assert status.field_errors == {}
    assert len(status.capabilities.fields) == fields
    assert status.supports("rx_power")
    assert status.supports("onu_state") == (mode == "gpon")
    assert status.supports("epon_llid_0_status") == (mode == "epon")
    assert status.capabilities.optional_fields == (
        frozenset({"device_name"}) if mode == "epon" else frozenset()
    )


@pytest.mark.parametrize("firmware", ["V9.99-new", "N/A"])
async def test_unknown_firmware_uses_schema_without_inheriting_a_quirk(
    epon_device_html, epon_pon_html, firmware
):
    status = await read_pages(epon_device_html.replace("V2.11.00P3T1", firmware), epon_pon_html)
    assert status.profile_id == "boa"
    assert status.pon_mode == "epon"
    assert status.values["epon_llid_0_status"] == 1
    assert status.values["rx_power"] == -18.1
    assert set(status.field_errors) == {"device_name"}
    assert status.capabilities.optional_fields == frozenset()


async def test_firmware_hint_does_not_override_page_detected_mode(device_html, pon_html):
    status = await read_pages(device_html.replace("V1.0-220923", "V2.11.00P3T1"), pon_html)
    assert status.profile_id == "boa"
    assert status.pon_mode == "gpon"
    assert status.values["onu_state"] == "O5"
    assert status.field_errors == {}


async def test_ambiguous_profiles_reject_snapshot(device_html, pon_html, monkeypatch):
    monkeypatch.setattr(
        profiles,
        "PROFILES",
        (
            BoaProfile("first", firmware_version="V1.0-220923"),
            BoaProfile("second", firmware_version="V1.0-220923"),
        ),
    )
    with pytest.raises(OnuParseError, match="Ambiguous"):
        await read_pages(device_html, pon_html)


@pytest.mark.parametrize(
    "replacement, expected_errors", [("Missing CPU", set()), ("CPU Usage", {"cpu_usage"})]
)
async def test_optional_fields_only_suppress_absence_not_invalid_values(
    device_html, pon_html, monkeypatch, replacement, expected_errors
):
    monkeypatch.setattr(
        profiles,
        "PROFILES",
        (BoaProfile("optional-cpu", optional_fields=frozenset({"cpu_usage"})),),
    )
    status = await read_pages(
        device_html.replace("CPU Usage", replacement).replace(">0%<", ">invalid%<"), pon_html
    )
    assert status.supports("cpu_usage")
    assert status.values["cpu_usage"] is None
    assert set(status.field_errors) == expected_errors
    assert status.capabilities.optional_fields == frozenset({"cpu_usage"})


async def test_unsupported_readings_are_distinct_from_parse_failures(
    device_html, pon_html, monkeypatch
):
    monkeypatch.setattr(
        profiles,
        "PROFILES",
        (BoaProfile("no-cpu", unsupported_fields=frozenset({"cpu_usage"})),),
    )
    status = await read_pages(device_html.replace(">0%<", ">broken%<"), pon_html)
    assert not status.supports("cpu_usage")
    assert status.values["cpu_usage"] is None
    assert status.field_errors == {}
    monkeypatch.setattr(profiles, "PROFILES", ())
    broken = await read_pages(device_html.replace(">0%<", ">broken%<"), pon_html)
    assert broken.supports("cpu_usage")
    assert broken.values["cpu_usage"] is None
    assert set(broken.field_errors) == {"cpu_usage"}


@pytest.mark.parametrize("kind", ["optional_fields", "unsupported_fields"])
def test_profile_cannot_disable_mac_identity(kind):
    with pytest.raises(ValueError, match="MAC identity"):
        BoaProfile("bad-profile", **{kind: frozenset({"mac_address"})})


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "https://other.example/status.asp"),
        ("GET", "//other.example/status.asp"),
        ("GET", "/status.asp?apply=settings"),
        ("POST", "/status.asp#fragment"),
        ("GET", "/tools/../status.asp"),
        ("GET", "/tools/%2e%2e/status.asp"),
        ("GET", "/./status.asp"),
        ("DELETE", "/status.asp"),
    ],
)
async def test_transport_rejects_unsafe_paths_even_in_an_adapter_policy(method, path):
    adapter = BoaAdapter()
    policy = replace(adapter.policy, allowed_requests=frozenset({(method, path)}))
    async with aiohttp.ClientSession() as session:
        transport = OnuTransport(session, "http://192.0.2.1", "reader", "secret", policy)
        with patch.object(session, "get") as get, patch.object(session, "post") as post:
            with pytest.raises(OnuConnectionError, match="Unsupported"):
                await transport.request(
                    method,
                    path,
                    None,
                    validate_response=lambda _status, _target: None,
                    is_login_error=adapter.is_login_error,
                )
            get.assert_not_called()
            post.assert_not_called()


async def test_transport_enforces_selected_policy_before_requesting(onu_server):
    host, _, requests = onu_server
    adapter = BoaAdapter()
    adapter.policy = HttpPolicy(frozenset({("GET", PON_STATUS_PATH)}))
    async with aiohttp.ClientSession() as session:
        with pytest.raises(OnuConnectionError, match="Unsupported"):
            await OnuClient(session, host, adapter=adapter).async_get_status()
    assert requests == []


class JsonFixtureAdapter:
    """A synthetic family proving the shared client does not parse Boa pages itself."""

    policy = HttpPolicy(frozenset({("GET", DEVICE_STATUS_PATH)}))
    login_page_path = "/unused-login"
    login_form_path = "/unused-auth"
    logout_form_path = "/unused-logout"

    async def async_read_status(self, request):
        import json

        values = json.loads(await request("GET", DEVICE_STATUS_PATH))
        return OnuStatus(
            values=values,
            mac_address="02:00:00:00:00:01",
            profile_id="test-json",
            capabilities=OnuCapabilities(frozenset(values)),
        )

    @staticmethod
    def validate_response(method, path, status, redirect_path):
        assert method == "GET" and path == DEVICE_STATUS_PATH and status == 200

    @staticmethod
    def is_login_error(status, message):
        return False

    @staticmethod
    def login_payload(html, host, username, password):
        raise AssertionError("Fixture adapter never authenticates")

    @staticmethod
    def login_result(html):
        raise AssertionError("Fixture adapter never authenticates")

    @staticmethod
    def logout_payload():
        raise AssertionError("Fixture adapter never logs out")

    @staticmethod
    def validate_logout(html):
        raise AssertionError("Fixture adapter never logs out")


async def test_client_accepts_a_different_family_without_boa_parsing(onu_server):
    host, state, requests = onu_server
    state["device"] = '{"rx_power": -20.0}'
    async with aiohttp.ClientSession() as session:
        status = await OnuClient(
            session, host, adapter=JsonFixtureAdapter(), logout_after_poll=True
        ).async_get_status()
    assert status.profile_id == "test-json"
    assert status.values == {"rx_power": -20.0}
    assert status.supports("rx_power")
    assert requests == [("GET", DEVICE_STATUS_PATH, None)]
    assert not state["login_posts"] and not state["logout_posts"]


async def test_shared_entities_accept_an_adapter_without_optional_metadata(hass, onu_server):
    host, state, _ = onu_server
    state["device"] = '{"rx_power": -20.0}'

    def make_client(*args, **kwargs):
        return OnuClient(*args, adapter=JsonFixtureAdapter(), **kwargs)

    # Inject an interface family at the factory boundary. Setup, HTTP requests,
    # the coordinator, and entity registration still use their real implementations.
    with patch("custom_components.xpon_onu_stick.client.OnuClient", side_effect=make_client):
        result = await hass.config_entries.flow.async_init(
            "xpon_onu_stick", context={"source": "user"}, data={CONF_HOST: host}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
    assert result["result"].state is ConfigEntryState.LOADED
    sensors = hass.states.async_all("sensor")
    assert len(sensors) == 2  # Rx power and its related friendly status.
    assert {sensor.state for sensor in sensors} == {"-20.0", "good"}
    assert not state["login_posts"] and not state["logout_posts"]
