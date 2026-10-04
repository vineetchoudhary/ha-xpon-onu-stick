"""Check threshold boundaries, user limits, and GPON registration meanings."""

import pytest

from custom_components.xpon_onu_stick.health import (
    LIMIT_DEFAULTS,
    ONU_STATES,
    measurement_status,
    registration_status,
    validate_limits,
)


@pytest.mark.parametrize(
    "measurement, reading, expected",
    [
        ("rx_power", -27.001, "low"),
        ("rx_power", -27, "weak"),
        ("rx_power", -26.382721, "weak"),
        ("rx_power", -25, "weak"),
        ("rx_power", -24.999, "good"),
        ("rx_power", -10.001, "good"),
        ("rx_power", -10, "strong"),
        ("rx_power", -8, "strong"),
        ("rx_power", -7.999, "high"),
        ("tx_power", 0.499, "low"),
        ("tx_power", 0.5, "good"),
        ("tx_power", 1.869319, "good"),
        ("tx_power", 5, "good"),
        ("tx_power", 5.001, "high"),
        ("temperature", -0.001, "low"),
        ("temperature", 0, "good"),
        ("temperature", 37.613281, "good"),
        ("temperature", 59.999, "good"),
        ("temperature", 60, "warm"),
        ("temperature", 69.999, "warm"),
        ("temperature", 70, "high"),
        ("voltage", 3.1349, "low"),
        ("voltage", 3.135, "good"),
        ("voltage", 3.2483, "good"),
        ("voltage", 3.465, "good"),
        ("voltage", 3.4651, "high"),
        ("bias_current", 11.1, "limits_not_set"),
        ("bias_current", 0, "limits_not_set"),
        ("bias_current", -1, "invalid"),
    ],
)
def test_reference_limits_and_boundaries(measurement, reading, expected):
    result = measurement_status(measurement, reading, {})
    assert result.state == expected
    assert result.attributes["reading"] == reading
    assert result.attributes["description"]


@pytest.mark.parametrize(
    "measurement", ["rx_power", "tx_power", "temperature", "voltage", "bias_current"]
)
@pytest.mark.parametrize("reading", [None, float("nan"), float("inf")])
def test_absent_readings_are_unknown(measurement, reading):
    result = measurement_status(measurement, reading, {})
    assert result.state is None
    assert result.attributes["reading"] is None


@pytest.mark.parametrize(
    "reading, expected", [(4.9, "low"), (5, "good"), (11.1, "good"), (20, "good"), (20.1, "high")]
)
def test_module_specific_bias_current_range(reading, expected):
    result = measurement_status(
        "bias_current", reading, {"bias_current_min": 5, "bias_current_max": 20}
    )
    assert result.state == expected


def test_custom_optics_and_temperature_limits():
    assert measurement_status("rx_power", -26.382721, {"rx_power_min": -30}).state == "good"
    assert measurement_status("temperature", 75, {"temperature_max": 85}).state == "warm"
    assert measurement_status("rx_power", -27, {"rx_power_warning_margin": 0}).state == "good"
    assert measurement_status("rx_power", -8, {"rx_power_warning_margin": 0}).state == "good"
    result = measurement_status("rx_power", -26.382721, {})
    assert result.attributes["lower_margin_db"] == 0.617279
    assert result.attributes["upper_margin_db"] == 18.382721


@pytest.mark.parametrize("code", ONU_STATES)
def test_registration_states_include_explanations(code):
    result = registration_status(code)
    assert result.state == ONU_STATES[code][0]
    assert result.attributes == {"onu_state": code, "description": ONU_STATES[code][1]}
    assert registration_status(f" {code.lower()} ").state == result.state


def test_unknown_registration_states():
    assert registration_status(None).state is None
    assert registration_status("").state is None
    assert registration_status("O9").state == "unrecognized"
    assert registration_status("O9").attributes["onu_state"] == "O9"


@pytest.mark.parametrize(
    "limits, field",
    [
        ({"rx_power_min": -8, "rx_power_max": -27}, "rx_power_max"),
        ({"tx_power_min": 5, "tx_power_max": 5}, "tx_power_max"),
        ({"voltage_min": -1}, "voltage_min"),
        ({"bias_current_min": -1, "bias_current_max": 20}, "bias_current_min"),
        ({"temperature_warning": 70}, "temperature_warning"),
        ({"temperature_warning": -1}, "temperature_warning"),
        ({"rx_power_warning_margin": 9.5}, "rx_power_warning_margin"),
        ({"rx_power_warning_margin": -1}, "rx_power_warning_margin"),
        ({"bias_current_min": 5}, "base"),
        ({"bias_current_max": 20}, "base"),
        ({"voltage_max": float("inf")}, "voltage_max"),
        ({"temperature_max": float("nan")}, "temperature_max"),
        ({"rx_power_min": True}, "rx_power_min"),
    ],
)
def test_invalid_status_limits_are_rejected(limits, field):
    assert field in validate_limits(limits)


def test_valid_status_limits():
    assert validate_limits({}) == {}
    assert validate_limits({**LIMIT_DEFAULTS, "bias_current_min": 0, "bias_current_max": 20}) == {}
