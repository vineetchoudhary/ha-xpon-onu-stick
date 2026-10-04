"""Verify setup flows and entity lifecycle in the real Home Assistant runtime."""

from unittest.mock import patch

import aiohttp
import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.data_entry_flow import FlowManagerIndexView

from custom_components.xpon_onu_stick.api import (
    DEVICE_FIELDS,
    PON_FIELDS,
    OnuAuthError,
    OnuConnectionError,
    OnuStatus,
    parse_status_page,
)
from custom_components.xpon_onu_stick.const import DOMAIN


async def add_device(hass, host):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={CONF_HOST: host}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result["result"]


async def test_initial_setup_requires_an_address_and_never_uses_a_fallback(hass):
    with patch("custom_components.xpon_onu_stick.config_flow.OnuClient.async_get_status") as fetch:
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert result["type"] is FlowResultType.FORM
        schema = result["data_schema"]
        host_field = next(field for field in schema.schema if field.schema == CONF_HOST)
        assert host_field.default is vol.UNDEFINED
        with pytest.raises(vol.Invalid):
            schema({})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: ""})
        assert result["errors"] == {CONF_HOST: "invalid_host"}
        fetch.assert_not_called()


async def test_setup_all_readings_and_friendly_statuses_and_unload(hass, onu_server):
    host, _, requests = onu_server
    entry = await add_device(hass, host)
    assert entry.state is ConfigEntryState.LOADED
    states = {state.entity_id: state for state in hass.states.async_all("sensor")}
    assert len(states) == 22
    assert states["sensor.aot5222zy_rx_power"].state == "-26.382721"
    assert states["sensor.aot5222zy_rx_power"].attributes["unit_of_measurement"] == "dBm"
    assert states["sensor.aot5222zy_temperature"].attributes["state_class"] == "measurement"
    assert states["sensor.aot5222zy_bias_current"].attributes["unit_of_measurement"] == "mA"
    assert states["sensor.aot5222zy_uptime"].state == "1:21"
    assert states["sensor.aot5222zy_onu_state"].state == "O5"
    assert states["sensor.aot5222zy_onu_id"].state == "0"
    assert states["sensor.aot5222zy_rx_power_status"].state == "weak"
    assert states["sensor.aot5222zy_tx_power_status"].state == "good"
    assert states["sensor.aot5222zy_temperature_status"].state == "good"
    assert states["sensor.aot5222zy_voltage_status"].state == "good"
    assert states["sensor.aot5222zy_bias_current_status"].state == "limits_not_set"
    registration = states["sensor.aot5222zy_onu_registration_status"]
    assert registration.state == "connected"
    assert registration.attributes["onu_state"] == "O5"
    assert "established" in states["sensor.aot5222zy_onu_state"].attributes["description"]
    assert entry.unique_id == "02:00:00:00:00:01"
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 22
    assert len({entity.unique_id for entity in entities}) == 22
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    assert devices[0].model == "AOT5222ZY"
    assert devices[0].sw_version == "V1.0-220923"
    assert devices[0].configuration_url == host
    assert requests == [("GET", "/status.asp", None), ("GET", "/status_pon.asp", None)] * 2
    coordinator = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not coordinator._listeners
    assert coordinator._unsub_refresh is None
    assert all(state.state == "unavailable" for state in hass.states.async_all("sensor"))


async def test_failed_poll_marks_every_sensor_unavailable_then_recovers(hass, onu_server):
    host, state, _ = onu_server
    entry = await add_device(hass, host)
    state["status"] = 500
    await entry.runtime_data.async_refresh()
    assert all(sensor.state == "unavailable" for sensor in hass.states.async_all("sensor"))
    state["status"] = 200
    state["pon"] = state["pon"].replace("37.277344 C", "40.000000 C")
    await entry.runtime_data.async_refresh()
    assert hass.states.get("sensor.aot5222zy_temperature").state == "40.0"
    assert hass.states.get("sensor.aot5222zy_onu_state").state == "O5"
    assert hass.states.get("sensor.aot5222zy_temperature_status").state == "good"
    assert hass.states.get("sensor.aot5222zy_onu_registration_status").state == "connected"


async def test_friendly_statuses_follow_new_readings_on_the_shared_poll(hass, onu_server):
    host, state, requests = onu_server
    entry = await add_device(hass, host)
    state["pon"] = (
        state["pon"]
        .replace("37.277344 C", "65 C")
        .replace("3.256100 V", "3.1 V")
        .replace("1.939900  dBm", "5.5 dBm")
        .replace("-26.382721  dBm", "-28 dBm")
        .replace("11.150000 mA", "N/A")
        .replace(">O5<", ">O6<")
    )
    requests.clear()
    await entry.runtime_data.async_refresh()
    expected = {
        "temperature_status": "warm",
        "voltage_status": "low",
        "tx_power_status": "high",
        "rx_power_status": "low",
        "bias_current_status": "unknown",
        "onu_registration_status": "recovering",
    }
    for name, value in expected.items():
        assert hass.states.get(f"sensor.aot5222zy_{name}").state == value
    assert hass.states.get("sensor.aot5222zy_temperature").state == "65.0"
    assert hass.states.get("sensor.aot5222zy_rx_power").state == "-28.0"
    assert hass.states.get("sensor.aot5222zy_bias_current").state == "unknown"
    assert hass.states.get("sensor.aot5222zy_onu_state").state == "O6"
    assert requests == [("GET", "/status.asp", None), ("GET", "/status_pon.asp", None)]


async def test_missing_readings_and_unrecognized_registration_state(hass, onu_server):
    host, state, _ = onu_server
    entry = await add_device(hass, host)
    for value in ("37.277344 C", "3.256100 V", "1.939900  dBm", "-26.382721  dBm"):
        state["pon"] = state["pon"].replace(value, "N/A")
    state["pon"] = state["pon"].replace(">O5<", ">O9<")
    await entry.runtime_data.async_refresh()
    for name in ("temperature", "voltage", "tx_power", "rx_power"):
        assert hass.states.get(f"sensor.aot5222zy_{name}").state == "unknown"
        status = hass.states.get(f"sensor.aot5222zy_{name}_status")
        assert status.state == "unknown"
        assert status.attributes["reading"] is None
    assert hass.states.get("sensor.aot5222zy_onu_state").state == "O9"
    status = hass.states.get("sensor.aot5222zy_onu_registration_status")
    assert status.state == "unrecognized"
    assert status.attributes["onu_state"] == "O9"


async def test_replaced_device_does_not_change_existing_identity(hass, onu_server):
    host, state, _ = onu_server
    entry = await add_device(hass, host)
    state["device"] = state["device"].replace("020000000001", "001122334455")
    await entry.runtime_data.async_refresh()
    assert entry.unique_id == "02:00:00:00:00:01"
    assert all(sensor.state == "unavailable" for sensor in hass.states.async_all("sensor"))


async def test_duplicate_device(hass, onu_server):
    host, _, _ = onu_server
    await add_device(hass, host)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={CONF_HOST: host}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    "error, expected", [(OnuAuthError(), "invalid_auth"), (OnuConnectionError(), "cannot_connect")]
)
async def test_flow_errors(hass, error, expected):
    with patch(
        "custom_components.xpon_onu_stick.config_flow.OnuClient.async_get_status",
        side_effect=error,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data={CONF_HOST: "onu.example"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_bad_host_and_missing_username_never_fetch(hass):
    with patch("custom_components.xpon_onu_stick.config_flow.OnuClient.async_get_status") as fetch:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data={CONF_HOST: "http://onu/reboot.asp"}
        )
        assert result["errors"] == {CONF_HOST: "invalid_host"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "onu.example", CONF_PASSWORD: "secret"}
        )
        assert result["errors"] == {CONF_USERNAME: "username_required"}
        fetch.assert_not_called()


async def test_options_change_polling_interval_and_reload(hass, onu_server):
    host, _, _ = onu_server
    entry = await add_device(hass, host)
    old_coordinator = entry.runtime_data
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "polling"}
    )
    schema = result["data_schema"]
    for invalid in (0, 9, 3601):
        with pytest.raises(vol.Invalid):
            schema({CONF_SCAN_INTERVAL: invalid})
    await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SCAN_INTERVAL: 60})
    await hass.async_block_till_done()
    assert entry.options[CONF_SCAN_INTERVAL] == 60
    assert entry.runtime_data is not old_coordinator
    assert entry.runtime_data.update_interval.total_seconds() == 60
    assert len(hass.states.async_all("sensor")) == 22


async def open_status_limits(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "status_limits"}
    )


async def test_status_limit_form_serializes_numeric_fields_and_optional_bias(hass, onu_server):
    host, _, _ = onu_server
    entry = await add_device(hass, host)
    result = await open_status_limits(hass, entry)
    serialized = FlowManagerIndexView(hass.config_entries.options)._prepare_result_json(result)
    fields = {field["name"]: field for field in serialized["data_schema"]}
    assert len(fields) == 12
    assert fields["voltage_min"]["selector"]["number"] == {
        "mode": "box",
        "step": "any",
        "unit_of_measurement": "V",
    }
    assert fields["rx_power_warning_margin"]["selector"]["number"]["unit_of_measurement"] == "dB"
    assert fields["temperature_warning"]["selector"]["number"]["unit_of_measurement"] == "°C"
    assert fields["bias_current_min"]["optional"]
    assert fields["bias_current_min"]["allow_none"]
    assert "default" not in fields["bias_current_min"]


async def test_status_limits_reload_sensors_and_survive_polling_changes(hass, onu_server):
    host, _, requests = onu_server
    entry = await add_device(hass, host)
    ids_before = {sensor.entity_id for sensor in hass.states.async_all("sensor")}
    old_coordinator = entry.runtime_data
    result = await open_status_limits(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"rx_power_min": -30, "bias_current_min": 5, "bias_current_max": 20},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.runtime_data is not old_coordinator
    assert entry.runtime_data.update_interval.total_seconds() == 30
    assert hass.states.get("sensor.aot5222zy_rx_power_status").state == "good"
    assert hass.states.get("sensor.aot5222zy_bias_current_status").state == "good"
    assert hass.states.get("sensor.aot5222zy_rx_power").state == "-26.382721"
    assert {sensor.entity_id for sensor in hass.states.async_all("sensor")} == ids_before

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "polling"}
    )
    await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SCAN_INTERVAL: 60})
    await hass.async_block_till_done()
    assert entry.options["rx_power_min"] == -30
    assert entry.options["bias_current_min"] == 5
    assert entry.options["bias_current_max"] == 20
    assert entry.runtime_data.update_interval.total_seconds() == 60
    assert hass.states.get("sensor.aot5222zy_bias_current_status").state == "good"
    assert all(
        method == "GET" and path in {"/status.asp", "/status_pon.asp"}
        for method, path, _ in requests
    )


@pytest.mark.parametrize("clear_values", [{}, {"bias_current_min": None, "bias_current_max": None}])
async def test_bias_limits_can_be_cleared_without_resetting_other_options(
    hass, onu_server, clear_values
):
    host, _, _ = onu_server
    entry = await add_device(hass, host)
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_SCAN_INTERVAL: 60,
            "rx_power_min": -30,
            "bias_current_min": 5,
            "bias_current_max": 20,
        },
    )
    result = await open_status_limits(hass, entry)
    fields = result["data_schema"].schema
    minimum_field = next(field for field in fields if field.schema == "bias_current_min")
    assert minimum_field.default is vol.UNDEFINED
    assert minimum_field.description == {"suggested_value": 5}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"rx_power_min": -30, **clear_values}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["bias_current_min"] is None
    assert entry.options["bias_current_max"] is None
    assert entry.options["rx_power_min"] == -30
    assert entry.options[CONF_SCAN_INTERVAL] == 60
    assert hass.states.get("sensor.aot5222zy_bias_current_status").state == "limits_not_set"


@pytest.mark.parametrize(
    "limits, expected",
    [
        (
            {"rx_power_min": -8},
            {"rx_power_max": "invalid_range", "rx_power_warning_margin": "invalid_rx_margin"},
        ),
        ({"temperature_warning": 70}, {"temperature_warning": "invalid_temperature_warning"}),
        ({"bias_current_min": 5}, {"base": "bias_limits_required"}),
        ({"voltage_min": -1}, {"voltage_min": "negative_limit"}),
    ],
)
async def test_invalid_status_limits_leave_existing_options_and_poll_untouched(
    hass, onu_server, limits, expected
):
    host, _, requests = onu_server
    entry = await add_device(hass, host)
    old_coordinator = entry.runtime_data
    result = await open_status_limits(hass, entry)
    requests.clear()
    result = await hass.config_entries.options.async_configure(result["flow_id"], limits)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == expected
    assert not entry.options
    assert entry.runtime_data is old_coordinator
    assert requests == []


async def test_all_friendly_sensor_states_have_english_labels(hass, onu_server):
    from homeassistant.helpers.translation import async_get_translations

    from custom_components.xpon_onu_stick.sensor import STATUS_SENSORS

    host, _, _ = onu_server
    await add_device(hass, host)
    translations = await async_get_translations(hass, "en", "entity", {DOMAIN})
    for description in STATUS_SENSORS:
        prefix = f"component.{DOMAIN}.entity.sensor.{description.translation_key}"
        assert translations[f"{prefix}.name"]
        assert all(translations[f"{prefix}.state.{option}"] for option in description.options)


async def test_reconfigure_preserves_entity_identity(hass, onu_server):
    host, _, _ = onu_server
    entry = await add_device(hass, host)
    ids_before = {state.entity_id for state in hass.states.async_all("sensor")}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    host_field = next(field for field in result["data_schema"].schema if field.schema == CONF_HOST)
    assert host_field.default() == host
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: host})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert {state.entity_id for state in hass.states.async_all("sensor")} == ids_before


async def test_reconfigure_rejects_different_device(hass, onu_server):
    host, state, _ = onu_server
    entry = await add_device(hass, host)
    state["device"] = state["device"].replace("020000000001", "001122334455")
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
        data={CONF_HOST: host},
    )
    assert result["reason"] == "unique_id_mismatch"
    assert entry.unique_id == "02:00:00:00:00:01"


async def test_auth_expiry_starts_reauth_and_restores_sensors(hass, onu_server):
    host, state, _ = onu_server
    entry = await add_device(hass, host)
    state["auth"] = aiohttp.encode_basic_auth("reader", "secret")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert all(sensor.state == "unavailable" for sensor in hass.states.async_all("sensor"))
    flows = hass.config_entries.flow.async_progress()
    flow = next(flow for flow in flows if flow["context"]["source"] == "reauth")
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USERNAME: "reader", CONF_PASSWORD: "secret"}
    )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data[CONF_USERNAME] == "reader"
    assert hass.states.get("sensor.aot5222zy_onu_state").state == "O5"


async def test_startup_connection_failure_is_retryable(hass, onu_server, device_html, pon_html):
    host, _, _ = onu_server
    snapshot = OnuStatus(
        {
            **parse_status_page(device_html, DEVICE_FIELDS),
            **parse_status_page(pon_html, PON_FIELDS),
        },
        "02:00:00:00:00:01",
    )
    # First call validates the flow; the startup refresh then loses connectivity.
    with patch(
        "custom_components.xpon_onu_stick.api.OnuClient.async_get_status",
        side_effect=[snapshot, OnuConnectionError()],
    ):
        entry = await add_device(hass, host)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.states.async_all("sensor")
