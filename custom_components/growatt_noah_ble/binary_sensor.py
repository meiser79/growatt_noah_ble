from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NoahConfigEntry
from .entity import NoahEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: NoahConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            NetworkSensor(coordinator, "network"),
            MqttProblemSensor(coordinator, "mqtt_problem"),
            BluetoothSensor(coordinator, "bluetooth"),
        ]
    )


class NetworkSensor(NoahEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.network_ok


class MqttProblemSensor(NoahEntity, BinarySensorEntity):
    """On when the NOAH's MQTT server differs from the configured one."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        mqtt_ok = self.coordinator.data.mqtt_ok
        return None if mqtt_ok is None else not mqtt_ok


class BluetoothSensor(NoahEntity, BinarySensorEntity):
    """Whether the last BLE session with the NOAH succeeded."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.reachable
