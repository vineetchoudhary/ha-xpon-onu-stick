"""Expose every Device Status and PON Status field as a sensor."""

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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OnuConfigEntry
from .const import DOMAIN
from .coordinator import OnuCoordinator
from .health import (
    MEASUREMENT_STATES,
    ONU_STATUS_OPTIONS,
    FriendlyStatus,
    measurement_status,
    registration_status,
)

PARALLEL_UPDATES = 0
SENSORS = (
    SensorEntityDescription(
        key="device_name",
        name="Device name",
        icon="mdi:router-network",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(key="uptime", name="Uptime", icon="mdi:timer-outline"),
    SensorEntityDescription(
        key="firmware_version",
        name="Firmware version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="cpu_usage",
        name="CPU usage",
        icon="mdi:cpu-64-bit",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="memory_usage",
        name="Memory usage",
        icon="mdi:memory",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ip_address",
        name="IP address",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="subnet_mask",
        name="Subnet mask",
        icon="mdi:ip-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="mac_address",
        name="MAC address",
        icon="mdi:network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="voltage",
        name="Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="tx_power",
        name="Tx power",
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="rx_power",
        name="Rx power",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="bias_current",
        name="Bias current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        suggested_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(key="onu_state", name="ONU state", icon="mdi:access-point-network"),
    SensorEntityDescription(key="onu_id", name="ONU ID", icon="mdi:identifier"),
    SensorEntityDescription(
        key="loid_status", name="LOID status", icon="mdi:account-check-outline"
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
    """Add original readings and friendly status sensors to one device."""
    async_add_entities(
        [OnuSensor(entry.runtime_data, description) for description in SENSORS]
        + [OnuStatusSensor(entry.runtime_data, description) for description in STATUS_SENSORS]
    )


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
            name=str(coordinator.data.values["device_name"]),
            model=str(coordinator.data.values["device_name"]),
            sw_version=coordinator.data.values["firmware_version"],
            configuration_url=coordinator.client.host,
        )

    @property
    def native_value(self) -> str | float | int | None:
        return self.coordinator.data.values.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.key == "onu_state":
            status = registration_status(self.coordinator.data.values.get("onu_state"))
            return {"description": status.attributes["description"]}
        return None


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
        return self._status.attributes
