"""Expose ODI OSS optical loss-of-signal and DDM flags."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OnuConfigEntry
from .coordinator import OnuCoordinator
from .devices.odi_oss.status import ALARM_KEYS

DESCRIPTIONS = tuple(
    BinarySensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for key in ALARM_KEYS
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the fixed set of ODI OSS optical flags."""
    async_add_entities(
        OdiOpticalAlarm(entry.runtime_data, description) for description in DESCRIPTIONS
    )


class OdiOpticalAlarm(CoordinatorEntity[OnuCoordinator], BinarySensorEntity):
    """Expose one optical alarm from the shared status snapshot."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: OnuCoordinator, description: BinarySensorEntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.unique_id}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.values.get(self.entity_description.key)
        return value if isinstance(value, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        error = self.coordinator.data.field_errors.get(self.entity_description.key)
        return {"parse_error": error} if error else None
