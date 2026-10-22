"""Expose every Device Status and PON Status field as a sensor."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.entity_registry import async_entries_for_config_entry, async_get
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OnuConfigEntry
from .api import GPON_FIELDS
from .const import DOMAIN, MAX_EPON_LLID_SENSORS
from .coordinator import OnuCoordinator
from .health import (
    MEASUREMENT_STATES,
    ONU_STATUS_OPTIONS,
    FriendlyStatus,
    measurement_status,
    registration_status,
)

PARALLEL_UPDATES = 0
_LOGGER = logging.getLogger(__name__)
GPON_SENSOR_KEYS = {*GPON_FIELDS.values(), "onu_registration_status"}
SENSORS = (
    SensorEntityDescription(
        key="device_name",
        translation_key="device_name",
        icon="mdi:router-network",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(key="uptime", translation_key="uptime", icon="mdi:timer-outline"),
    SensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        icon="mdi:cpu-64-bit",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="memory_usage",
        translation_key="memory_usage",
        icon="mdi:memory",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ip_address",
        translation_key="ip_address",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="subnet_mask",
        translation_key="subnet_mask",
        icon="mdi:ip-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="mac_address",
        translation_key="mac_address",
        icon="mdi:network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="tx_power",
        translation_key="tx_power",
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="rx_power",
        translation_key="rx_power",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="bias_current",
        translation_key="bias_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        suggested_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="onu_state", translation_key="onu_state", icon="mdi:access-point-network"
    ),
    SensorEntityDescription(key="onu_id", translation_key="onu_id", icon="mdi:identifier"),
    SensorEntityDescription(
        key="loid_status", translation_key="loid_status", icon="mdi:account-check-outline"
    ),
)
STATUS_SENSORS = tuple(
    SensorEntityDescription(
        key=f"{measurement}_status",
        translation_key=f"{measurement}_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(states),
        icon="mdi:check-circle-outline",
    )
    for measurement, states in MEASUREMENT_STATES.items()
) + (
    SensorEntityDescription(
        key="onu_registration_status",
        translation_key="onu_registration_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(ONU_STATUS_OPTIONS),
        icon="mdi:access-point-network",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add sensors for the detected mode, including newly reported LLID indices."""
    coordinator = entry.runtime_data
    added: set[str] = set()
    prefix = f"{entry.unique_id}_"
    known_llids = {
        entity.unique_id.removeprefix(prefix)
        for entity in async_entries_for_config_entry(async_get(hass), entry.entry_id)
        if entity.unique_id.startswith(f"{prefix}epon_llid_")
    }
    limit_reported = False

    @callback
    def async_discover_sensors() -> None:
        nonlocal limit_reported
        if not coordinator.last_update_success:
            return
        descriptions = [(OnuSensor, description) for description in SENSORS]
        descriptions += [(OnuStatusSensor, description) for description in STATUS_SENSORS]
        if coordinator.data.pon_mode == "epon":
            descriptions = [
                (sensor_class, description)
                for sensor_class, description in descriptions
                if description.key not in GPON_SENSOR_KEYS
            ]
            descriptions += [
                (
                    OnuSensor,
                    SensorEntityDescription(
                        key=key,
                        name=f"EPON LLID {key.removeprefix('epon_llid_').removesuffix('_status')} status",
                        icon="mdi:access-point-network",
                    ),
                )
                for key in coordinator.data.values
                if key.startswith("epon_llid_")
            ]
        entities = []
        for sensor_class, description in descriptions:
            if description.key not in added:
                if description.key.startswith("epon_llid_"):
                    if (
                        description.key not in known_llids
                        and len(known_llids) >= MAX_EPON_LLID_SENSORS
                    ):
                        if not limit_reported:
                            _LOGGER.warning(
                                "Ignoring new LLID indices for %s after %s diagnostic sensors",
                                coordinator.client.host,
                                MAX_EPON_LLID_SENSORS,
                            )
                            limit_reported = True
                        continue
                    known_llids.add(description.key)
                entities.append(sensor_class(coordinator, description))
                added.add(description.key)
        if entities:
            async_add_entities(entities)

    async_discover_sensors()
    entry.async_on_unload(coordinator.async_add_listener(async_discover_sensors))


class OnuSensor(CoordinatorEntity[OnuCoordinator], SensorEntity):
    """A read-only value from the shared status snapshot."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OnuCoordinator, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.unique_id)},
            connections={(CONNECTION_NETWORK_MAC, coordinator.data.mac_address)},
            name=coordinator.data.values["device_name"] or coordinator.entry.title,
            model=coordinator.data.values["device_name"],
            sw_version=coordinator.data.values["firmware_version"],
            configuration_url=coordinator.client.host,
        )

    @property
    def available(self) -> bool:
        key = self.entity_description.key
        if key in GPON_SENSOR_KEYS and self.coordinator.data.pon_mode != "gpon":
            return False
        if key.startswith("epon_llid_") and key not in self.coordinator.data.values:
            return False
        return super().available

    @property
    def native_value(self) -> str | float | int | None:
        return self.coordinator.data.values.get(self.entity_description.key)

    def _parse_error_attributes(self, key: str) -> dict[str, str]:
        """Expose the parsing problem on only the affected reading/status."""
        error = self.coordinator.data.field_errors.get(key)
        return {"parse_error": error} if error else {}

    @property
    def extra_state_attributes(self) -> dict | None:
        attributes = {
            "pon_mode": self.coordinator.data.pon_mode,
            **self._parse_error_attributes(self.entity_description.key),
        }
        if self.entity_description.key == "onu_state":
            status = registration_status(self.coordinator.data.values.get("onu_state"))
            attributes["description"] = status.attributes["description"]
        return attributes or None


class OnuStatusSensor(OnuSensor):
    """Explain a measurement or the GPON registration state using the shared poll."""

    @property
    def _status(self) -> FriendlyStatus:
        if self.entity_description.key == "onu_registration_status":
            return registration_status(self.coordinator.data.values.get("onu_state"))
        measurement = self.entity_description.key.removesuffix("_status")
        return measurement_status(
            measurement,
            self.coordinator.data.values.get(measurement),
            dict(self.coordinator.entry.options),
        )

    @property
    def native_value(self) -> str | None:
        return self._status.state

    @property
    def extra_state_attributes(self) -> dict:
        key = (
            "onu_state"
            if self.entity_description.key == "onu_registration_status"
            else self.entity_description.key.removesuffix("_status")
        )
        return {
            "pon_mode": self.coordinator.data.pon_mode,
            **self._status.attributes,
            **self._parse_error_attributes(key),
        }
