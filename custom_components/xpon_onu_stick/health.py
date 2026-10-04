"""Interpret reported readings using adjustable advisory limits."""

import math
from dataclasses import dataclass
from typing import Any

# GPON Class B+ reference values from ITU-T G.984.2, Table A.1.
# Temperature and voltage are generic SFP guidelines, not device alarm flags.
# Bias current has no universal healthy range and requires user-supplied limits.
LIMIT_DEFAULTS: dict[str, float | None] = {
    "rx_power_min": -27.0,
    "rx_power_max": -8.0,
    "rx_power_warning_margin": 2.0,
    "tx_power_min": 0.5,
    "tx_power_max": 5.0,
    "temperature_min": 0.0,
    "temperature_warning": 60.0,
    "temperature_max": 70.0,
    "voltage_min": 3.135,
    "voltage_max": 3.465,
    "bias_current_min": None,
    "bias_current_max": None,
}
MEASUREMENT_UNITS = {
    "rx_power": "dBm",
    "tx_power": "dBm",
    "temperature": "°C",
    "voltage": "V",
    "bias_current": "mA",
}
MEASUREMENT_STATES = {
    "rx_power": ("good", "weak", "low", "strong", "high"),
    "tx_power": ("good", "low", "high"),
    "temperature": ("good", "low", "warm", "high"),
    "voltage": ("good", "low", "high"),
    "bias_current": ("good", "low", "high", "limits_not_set", "invalid"),
}
ONU_STATES = {
    "O1": (
        "initial",
        "The ONU is starting and checking its GPON connection before registration.",
    ),
    "O2": (
        "standby",
        "The ONU is receiving the provider's signal and waiting for registration parameters.",
    ),
    "O3": (
        "serial_number",
        "The ONU is exchanging its GPON serial number with the provider for identification.",
    ),
    "O4": (
        "ranging",
        "The provider is measuring the link delay and aligning the ONU's transmission timing.",
    ),
    "O5": (
        "connected",
        "The GPON optical connection is established with the provider.",
    ),
    "O6": (
        "recovering",
        "The ONU detected a loss of signal or framing and is trying to recover the connection.",
    ),
    "O7": (
        "disabled",
        "The provider has disabled upstream transmission. The ONU is waiting to be enabled.",
    ),
}
ONU_STATUS_OPTIONS = tuple(state for state, _ in ONU_STATES.values()) + ("unrecognized",)


@dataclass(frozen=True)
class FriendlyStatus:
    """A stable enum state and details explaining the classification."""

    state: str | None
    attributes: dict[str, Any]


def validate_limits(options: dict[str, Any]) -> dict[str, str]:
    """Reject incomplete, non-finite, or contradictory user limits."""
    limits = {**LIMIT_DEFAULTS, **options}
    errors: dict[str, str] = {}
    for key in LIMIT_DEFAULTS:
        value = limits[key]
        if value is None and key.startswith("bias_current_"):
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            errors[key] = "invalid_limit"
    if errors:
        return errors
    for measurement in MEASUREMENT_UNITS:
        minimum, maximum = limits[f"{measurement}_min"], limits[f"{measurement}_max"]
        if (minimum is None) != (maximum is None):
            errors["base"] = "bias_limits_required"
        elif minimum is not None and maximum is not None and minimum >= maximum:
            errors[f"{measurement}_max"] = "invalid_range"
    for key in ("voltage_min", "voltage_max", "bias_current_min", "bias_current_max"):
        if limits[key] is not None and limits[key] < 0:
            errors[key] = "negative_limit"
    warning = limits["temperature_warning"]
    if not limits["temperature_min"] <= warning < limits["temperature_max"]:
        errors["temperature_warning"] = "invalid_temperature_warning"
    margin = limits["rx_power_warning_margin"]
    if margin < 0 or margin * 2 >= limits["rx_power_max"] - limits["rx_power_min"]:
        errors["rx_power_warning_margin"] = "invalid_rx_margin"
    return errors


def measurement_status(
    measurement: str, reading: float | int | None, options: dict[str, Any]
) -> FriendlyStatus:
    """Classify a reading without altering its original value."""
    limits = {**LIMIT_DEFAULTS, **options}
    minimum, maximum = limits[f"{measurement}_min"], limits[f"{measurement}_max"]
    attributes: dict[str, Any] = {
        "reading": reading,
        "measurement_unit": MEASUREMENT_UNITS[measurement],
        "minimum": minimum,
        "maximum": maximum,
    }
    if reading is None or not math.isfinite(reading):
        return FriendlyStatus(
            None, {**attributes, "reading": None, "description": "No measurement is available."}
        )
    if measurement == "bias_current" and reading < 0:
        state, description = "invalid", "The device reported a negative laser bias current."
    elif minimum is None or maximum is None:
        state, description = (
            "limits_not_set",
            "Set the module's minimum and maximum bias current in the integration's status limits.",
        )
    elif reading < minimum:
        state, description = "low", "The reading is below the configured minimum."
    elif reading > maximum or (measurement == "temperature" and reading >= maximum):
        state, description = (
            "high",
            "The reading has reached or exceeded the configured upper limit.",
        )
    elif measurement == "temperature" and reading >= limits["temperature_warning"]:
        state, description = "warm", "The temperature is approaching the configured upper limit."
    elif (
        measurement == "rx_power"
        and limits["rx_power_warning_margin"] > 0
        and reading <= minimum + limits["rx_power_warning_margin"]
    ):
        state, description = "weak", "Receive power is close to the configured minimum."
    elif (
        measurement == "rx_power"
        and limits["rx_power_warning_margin"] > 0
        and reading >= maximum - limits["rx_power_warning_margin"]
    ):
        state, description = "strong", "Receive power is close to the configured maximum."
    else:
        state, description = "good", "The reading is within the configured normal range."
    if measurement == "rx_power":
        attributes.update(
            warning_margin=limits["rx_power_warning_margin"],
            lower_margin_db=round(reading - minimum, 6),
            upper_margin_db=round(maximum - reading, 6),
        )
    elif measurement == "temperature":
        attributes["warning_threshold"] = limits["temperature_warning"]
    return FriendlyStatus(state, {**attributes, "description": description})


def registration_status(raw_state: str | None) -> FriendlyStatus:
    """Explain O1 to O7 while preserving the original firmware code."""
    if not raw_state:
        return FriendlyStatus(
            None, {"onu_state": raw_state, "description": "No ONU state is available."}
        )
    state, description = ONU_STATES.get(
        raw_state.strip().upper(),
        ("unrecognized", "The device reported an unrecognized GPON registration state."),
    )
    return FriendlyStatus(state, {"onu_state": raw_state, "description": description})
