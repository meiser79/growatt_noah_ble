from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as p
from .coordinator import NoahConfigEntry, NoahData
from .entity import NoahEntity


@dataclass(frozen=True, kw_only=True)
class NoahSensorDescription(SensorEntityDescription):
    value: Callable[[NoahData], Any]


def _param(param_id: int) -> Callable[[NoahData], Any]:
    return lambda data: data.params.get(param_id)


SENSORS = [
    NoahSensorDescription(key="mqtt_server", value=_param(p.P_MQTT_HOST_ACTIVE)),
    NoahSensorDescription(
        key="mqtt_server_configured", value=_param(p.P_MQTT_HOST), entity_category=EntityCategory.DIAGNOSTIC
    ),
    NoahSensorDescription(
        key="mqtt_port_configured", value=_param(p.P_MQTT_PORT), entity_category=EntityCategory.DIAGNOSTIC
    ),
    NoahSensorDescription(key="firmware", value=_param(p.P_FIRMWARE), entity_category=EntityCategory.DIAGNOSTIC),
    NoahSensorDescription(
        key="mac",
        value=_param(p.P_MAC),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    NoahSensorDescription(
        key="last_contact",
        value=lambda data: data.last_contact,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    NoahSensorDescription(
        key="last_mqtt_fix",
        value=lambda data: data.last_mqtt_fix,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    NoahSensorDescription(
        key="last_wifi_fix",
        value=lambda data: data.last_wifi_fix,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: NoahConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(NoahSensor(entry.runtime_data, d) for d in SENSORS)


class NoahSensor(NoahEntity, SensorEntity):
    entity_description: NoahSensorDescription

    def __init__(self, coordinator, description: NoahSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value(self.coordinator.data)
