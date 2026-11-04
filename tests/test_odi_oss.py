"""ODI OSS capture, local SSH transport, and Home Assistant regressions."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import asyncssh
import pytest
import pytest_asyncio
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.xpon_onu_stick.const import (
    CONF_CONNECTION_TYPE,
    CONF_SSH_FINGERPRINT,
    CONF_SSH_KEY_FILE,
    CONNECTION_ODI_SSH,
    DOMAIN,
)
from custom_components.xpon_onu_stick.devices.odi_oss import ssh
from custom_components.xpon_onu_stick.devices.odi_oss.status import STATUS_COMMAND, OdiStatusParser
from custom_components.xpon_onu_stick.models import OnuAuthError, OnuConnectionError, OnuParseError

_CAPTURE = Path(__file__).parent / "fixtures/devices/odi-dfp-34x-2c2/odi-oss-v1.15.0/ssh_status.txt"
_MAC = "02:00:00:00:00:01"
_OTHER_MAC = "02:00:00:00:00:02"


@pytest.fixture
def captured_status():
    return _CAPTURE.read_text()


def _replace_section(output, name, content):
    before, rest = output.split(f"XPON-ODI-STATUS {name}\n", 1)
    _, after = rest.split("XPON-ODI-STATUS ", 1)
    return f"{before}XPON-ODI-STATUS {name}\n{content}XPON-ODI-STATUS {after}"


def test_odi_capture_parses_existing_and_diagnostic_readings(captured_status):
    status = OdiStatusParser().parse(captured_status)
    assert status.mac_address == _MAC
    assert status.pon_mode == "gpon"
    assert not status.supports("loid_status")
    assert not status.field_errors
    expected = {
        "firmware_version": "v1.15.0",
        "onu_state": "O5",
        "onu_id": 1,
        "temperature": 30.5,
        "voltage": 3.2639,
        "bias_current": 10.4,
        "tx_power": 2.060699,
        "rx_power": -26.777807,
        "ip_address": "192.0.2.10",
        "subnet_mask": "255.255.255.0",
        "uptime": "0:27:55",
        "cpu_usage": None,
        "memory_usage": pytest.approx(44.3406, abs=0.001),
        "optical_los": False,
        "optical_ddm_alarm": False,
        "optical_ddm_warning": False,
        "gpon_ds_bip_error_blocks": 2,
        "gpon_ds_fec_corrected_codewords": 0,
        "gpon_ds_fec_uncorrectable_codewords": 0,
        "gpon_los_events": 0,
        "gpon_los_duration": 0,
    }
    for key, value in expected.items():
        assert status.values[key] == value


@pytest.mark.parametrize(
    ("name", "content"),
    [("mac", "bad\n"), ("gpon", "serial masked\n"), ("build", "image=stock\n")],
)
def test_odi_rejects_invalid_required_sections(captured_status, name, content):
    with pytest.raises(OnuParseError):
        OdiStatusParser().parse(_replace_section(captured_status, name, content))


def test_odi_requires_complete_framed_reply(captured_status):
    parser = OdiStatusParser()
    for reply in ("login failed\n", captured_status.rsplit("XPON-ODI-STATUS ", 1)[0]):
        with pytest.raises(OnuParseError):
            parser.parse(reply)


def test_odi_field_errors_are_isolated_and_recover(captured_status):
    parser = OdiStatusParser()
    reply = (
        captured_status.replace("state 5 (O5)", "state 4 (O5)")
        .replace("onu_id 1", "onu_id 0")
        .replace("30.500000 C", "0 C")
        .replace("-26.777807  dBm", "-inf dBm")
        .replace("ctr ds_bip_err_blocks 2", "ctr ds_bip_err_blocks 18446744073709551616")
        .replace("Optical LOS, status: clear", "Optical LOS, status: corrupt")
        .replace(
            "Warning Temperature high, status: clear", "Warning Temperature high, status: occur"
        )
        .replace("alarm_ms los 0", "alarm_ms los 1200")
    )
    status = parser.parse(reply)
    assert set(status.field_errors) == {
        "onu_state",
        "rx_power",
        "optical_los",
        "gpon_ds_bip_error_blocks",
    }
    assert all(status.values[key] is None for key in status.field_errors)
    assert status.values["temperature"] == 0
    assert status.values["onu_id"] == 0
    assert status.values["optical_ddm_warning"] is True
    assert status.values["gpon_los_duration"] == 1.2
    assert not parser.parse(captured_status).field_errors


def test_odi_cpu_samples_and_driver_counter_reset(captured_status):
    parser = OdiStatusParser()
    assert parser.parse(captured_status).values["cpu_usage"] is None
    second = _replace_section(captured_status, "cpu", "cpu  931 0 7714 157564 0 0 872 0 0 0\n")
    assert parser.parse(second).values["cpu_usage"] == 25
    reset = _replace_section(second, "cpu", "cpu  1 0 2 30 0 0 1 0 0 0\n").replace(
        "ctr ds_bip_err_blocks 2", "ctr ds_bip_err_blocks 0"
    )
    status = parser.parse(reset)
    assert status.values["cpu_usage"] is None
    assert status.values["gpon_ds_bip_error_blocks"] == 0
    assert not status.field_errors
    next_sample = _replace_section(reset, "cpu", "cpu  2 0 2 33 0 0 1 0 0 0\n")
    assert parser.parse(next_sample).values["cpu_usage"] == 25


@pytest_asyncio.fixture
async def odi_server(captured_status, tmp_path):
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    public_key = client_key.convert_to_public()
    key_dir = tmp_path / DOMAIN / "ssh"
    key_dir.mkdir(parents=True)
    key_path = key_dir / "onu"
    key_path.write_bytes(client_key.export_private_key())
    key_path.chmod(0o600)
    state = {
        "allowed_keys": {public_key},
        "attempted_keys": [],
        "reply": captured_status.encode(),
        "stderr": b"",
        "exit_status": 0,
        "commands": [],
        "connections": set(),
        "accepted": 0,
        "active_commands": 0,
        "max_concurrent": 0,
        "stall": False,
    }

    class Server(asyncssh.SSHServer):
        def connection_made(self, conn):
            self.conn = conn
            state["connections"].add(conn)
            state["accepted"] += 1

        def connection_lost(self, exc):
            state["connections"].discard(self.conn)

        def begin_auth(self, username):
            return True

        def public_key_auth_supported(self):
            return True

        def validate_public_key(self, username, key):
            state["attempted_keys"].append(key)
            return username == "root" and key in state["allowed_keys"]

    async def run_command(process):
        state["commands"].append(process.command)
        state["active_commands"] += 1
        state["max_concurrent"] = max(state["active_commands"], state["max_concurrent"])
        try:
            if state["stall"]:
                await process.wait_closed()
                return
            await asyncio.sleep(0.01)
            if process.command != STATUS_COMMAND:
                process.exit(127)
                return
            process.stdout.write(state["reply"])
            process.stderr.write(state["stderr"])
            process.exit(state["exit_status"])
        finally:
            state["active_commands"] -= 1

    async with await asyncssh.listen(
        "127.0.0.1",
        0,
        server_factory=Server,
        server_host_keys=[host_key],
        process_factory=run_command,
        encoding=None,
    ) as server:
        yield (
            {
                CONF_HOST: "127.0.0.1",
                CONF_PORT: server.get_port(),
                CONF_SSH_KEY_FILE: key_path.name,
                CONF_SSH_FINGERPRINT: host_key.get_fingerprint(),
                CONF_CONNECTION_TYPE: CONNECTION_ODI_SSH,
            },
            state,
            key_path,
        )
        await _drop_connections(state)


async def _drop_connections(state):
    connections = tuple(state["connections"])
    for connection in connections:
        connection.abort()
    await asyncio.gather(*(connection.wait_closed() for connection in connections))


def _client(data, key_path, **overrides):
    data = {**data, **overrides}
    return ssh.OdiSshClient(
        data[CONF_HOST],
        data[CONF_PORT],
        str(key_path.parents[2]),
        data[CONF_SSH_KEY_FILE],
        data[CONF_SSH_FINGERPRINT],
    )


async def test_ssh_reuses_connection_and_serializes_endpoint(odi_server):
    data, state, key_path = odi_server
    first, second = _client(data, key_path), _client(data, key_path)
    try:
        await asyncio.gather(first.async_get_status(), second.async_get_status())
        await first.async_get_status()
        assert state["accepted"] == 2
        assert state["max_concurrent"] == 1
        assert state["commands"] == [STATUS_COMMAND] * 3
    finally:
        await first.async_close()
        await second.async_close()


async def test_ssh_rejects_host_key_before_authentication(odi_server):
    data, state, key_path = odi_server
    fingerprint = asyncssh.generate_private_key("ssh-ed25519").get_fingerprint()
    client = _client(data, key_path, ssh_fingerprint=fingerprint)
    with patch("asyncssh.connection.GSSClient", wraps=asyncssh.connection.GSSClient) as gss_client:
        with pytest.raises(ssh.OnuHostKeyError):
            await client.async_get_status()
        gss_client.assert_not_called()
    assert not state["attempted_keys"]
    assert not state["commands"]


async def test_ssh_rejects_unenrolled_client_key(odi_server):
    data, state, key_path = odi_server
    state["allowed_keys"].clear()
    with pytest.raises(OnuAuthError, match="rejected"):
        await _client(data, key_path).async_get_status()
    assert state["attempted_keys"]
    assert not state["commands"]


@pytest.mark.parametrize("variant", ["traversal", "file_link", "directory_link", "public_mode"])
async def test_ssh_rejects_unsafe_key_files(odi_server, variant):
    data, state, key_path = odi_server
    if variant == "traversal":
        data[CONF_SSH_KEY_FILE] = "../onu"
    elif variant == "file_link":
        key_path.with_name("alias").symlink_to(key_path)
        data[CONF_SSH_KEY_FILE] = "alias"
    elif variant == "directory_link":
        outside = key_path.parents[2] / "keys"
        key_path.parent.rename(outside)
        key_path.parent.symlink_to(outside, target_is_directory=True)
    else:
        key_path.chmod(0o644)
    with pytest.raises(ssh.OnuKeyFileError):
        await _client(data, key_path).async_get_status()
    assert state["accepted"] == 0


@pytest.mark.parametrize("fault", ["stall", "stdout", "stderr", "exit_status"])
async def test_ssh_bounds_failed_poll_and_reconnects(odi_server, monkeypatch, fault):
    data, state, key_path = odi_server
    client = _client(data, key_path)
    await client.async_get_status()
    initial = state.copy()
    if fault == "stall":
        monkeypatch.setattr(ssh, "REQUEST_TIMEOUT", 0.1)
        state["stall"] = True
    elif fault == "exit_status":
        state["exit_status"] = 1
    elif fault == "stdout":
        state["reply"] = b"a" * (ssh._MAX_REPLY_BYTES + 1)
    else:
        state["stderr"] = b"a" * (ssh._MAX_REPLY_BYTES + 1)
    try:
        with pytest.raises(OnuConnectionError):
            await client.async_get_status()
        state["stall"] = False
        state["reply"] = initial["reply"]
        state["stderr"] = initial["stderr"]
        state["exit_status"] = initial["exit_status"]
        monkeypatch.setattr(ssh, "REQUEST_TIMEOUT", 10)
        assert (await client.async_get_status()).mac_address == _MAC
        assert state["accepted"] == 2
    finally:
        await client.async_close()


async def _choose(hass, method, *, source="user", entry=None):
    context = {"source": source}
    if entry:
        context["entry_id"] = entry.entry_id
    menu = await hass.config_entries.flow.async_init(DOMAIN, context=context)
    assert menu["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(menu["flow_id"], {"next_step_id": method})


def _entity(hass, key, platform="sensor"):
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{_MAC}_{key}")
    return hass.states.get(entity_id) if entity_id else None


async def _add_ssh(hass, data):
    form = await _choose(hass, "ssh")
    assert form["step_id"] == "ssh"
    assert form["type"] is FlowResultType.FORM
    payload = {key: value for key, value in data.items() if key != CONF_CONNECTION_TYPE}
    result = await hass.config_entries.flow.async_configure(form["flow_id"], payload)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert dict(entry.data) == data
    return entry


async def test_ha_ssh_setup_poll_failure_recovery_and_reload(hass, odi_server, captured_status):
    data, state, _ = odi_server
    entry = await _add_ssh(hass, data)
    assert entry.unique_id == _MAC
    assert _entity(hass, "onu_registration_status").state == "connected"
    assert _entity(hass, "loid_status") is None
    assert (
        _entity(hass, "gpon_ds_fec_corrected_codewords").attributes["state_class"]
        == "total_increasing"
    )
    assert _entity(hass, "gpon_los_duration").attributes["unit_of_measurement"] == "s"
    assert _entity(hass, "optical_los", "binary_sensor").state == "off"
    assert _entity(hass, "cpu_usage").state == "unknown"
    options = await hass.config_entries.options.async_init(entry.entry_id)
    assert options["menu_options"] == ["polling", "status_limits"]
    initial_connections = state["accepted"]
    state["reply"] = (
        captured_status.replace("Optical LOS, status: clear", "Optical LOS, status: occur")
        .replace("-26.777807  dBm", "-inf dBm")
        .encode()
    )
    await entry.runtime_data.async_refresh()
    assert _entity(hass, "rx_power").state == "unknown"
    assert "parse_error" in _entity(hass, "rx_power").attributes
    assert _entity(hass, "optical_los", "binary_sensor").state == "on"
    assert state["accepted"] == initial_connections
    state["reply"] = captured_status.replace(_MAC, _OTHER_MAC).encode()
    await entry.runtime_data.async_refresh()
    assert _entity(hass, "rx_power").state == "unavailable"
    assert _entity(hass, "optical_los", "binary_sensor").state == "unavailable"
    state["reply"] = captured_status.encode()
    await entry.runtime_data.async_refresh()
    rx = _entity(hass, "rx_power")
    assert rx.state == "-26.777807"
    assert "parse_error" not in rx.attributes
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _entity(hass, "rx_power").entity_id == rx.entity_id
    assert len(state["connections"]) == 1
    connection = next(iter(state["connections"]))
    assert await hass.config_entries.async_unload(entry.entry_id)
    await asyncio.wait_for(connection.wait_closed(), 1)
    assert not state["connections"]


async def test_ha_ssh_reauth_only_changes_key_file(hass, odi_server):
    data, state, key_path = odi_server
    entry = await _add_ssh(hass, data)
    replacement = asyncssh.generate_private_key("ssh-ed25519")
    new_file = key_path.with_name("rotated")
    new_file.write_bytes(replacement.export_private_key())
    new_file.chmod(0o600)
    state["allowed_keys"] = {replacement.convert_to_public()}
    connection = entry.runtime_data.client._connection
    await _drop_connections(state)
    await asyncio.wait_for(connection.wait_closed(), 1)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _entity(hass, "rx_power").state == "unavailable"
    flow = next(
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == "reauth"
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_SSH_KEY_FILE: new_file.name}
    )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert dict(entry.data) == {**data, CONF_SSH_KEY_FILE: "rotated"}
    assert _entity(hass, "rx_power").state == "-26.777807"


@pytest.mark.parametrize("matches", [True, False])
async def test_ha_reconfigure_boa_to_ssh_checks_identity(hass, onu_server, odi_server, matches):
    host, _, _ = onu_server
    data, state, _ = odi_server
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={CONF_HOST: host}
    )
    entry = result["result"]
    await hass.async_block_till_done()
    hass.config_entries.async_update_entry(entry, options={CONF_SCAN_INTERVAL: 60})
    rx_id = _entity(hass, "rx_power").entity_id
    if not matches:
        state["reply"] = state["reply"].replace(_MAC.encode(), _OTHER_MAC.encode())
    form = await _choose(hass, "ssh", source="reconfigure", entry=entry)
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {key: value for key, value in data.items() if key != CONF_CONNECTION_TYPE}
    )
    await hass.async_block_till_done()
    assert entry.unique_id == _MAC
    assert entry.options[CONF_SCAN_INTERVAL] == 60
    assert _entity(hass, "rx_power").entity_id == rx_id
    if matches:
        assert result["reason"] == "reconfigure_successful"
        assert dict(entry.data) == data
        assert _entity(hass, "gpon_ds_bip_error_blocks").state == "2"
        back = await _choose(hass, "boa", source="reconfigure", entry=entry)
        result = await hass.config_entries.flow.async_configure(back["flow_id"], {CONF_HOST: host})
        assert result["reason"] == "reconfigure_successful"
        await hass.async_block_till_done()
        assert CONF_SSH_KEY_FILE not in entry.data
        assert not state["connections"]
        assert _entity(hass, "rx_power").entity_id == rx_id
    else:
        assert result["reason"] == "unique_id_mismatch"
        assert entry.data[CONF_HOST] == host
        for connection in tuple(state["connections"]):
            await asyncio.wait_for(connection.wait_closed(), 1)
        assert not state["connections"]
