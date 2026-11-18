from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as p
from .coordinator import NoahConfigEntry, NoahData
from .entity import NoahEntity


@dataclass(frozen=True, kw_only=True)
class NoahSensorDescription(SensorEntityDescription):
    value: Callable[[NoahData], Any]
    attributes: Callable[[NoahData], dict[str, Any]] | None = None


def _param(param_id: int) -> Callable[[NoahData], Any]:
    return lambda data: data.params.get(param_id)


def _device_type(data: NoahData) -> str | None:
    code = data.params.get(p.P_DEVICE_TYPE)
    return p.DEVICE_TYPES.get(code, code)


def _int_param(param_id: int) -> Callable[[NoahData], int | None]:
    def value(data: NoahData) -> int | None:
        try:
            return int(data.params[param_id])
        except (KeyError, ValueError):
            return None

    return value


def _ip_address(data: NoahData) -> str | None:
    # the lease format is not documented; the logger's own address is assumed to be the first one in it
    match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", data.params.get(p.P_DHCP_LEASE_0, ""))
    return match.group(0) if match else None


def _dhcp_lease(data: NoahData) -> dict[str, Any]:
    # 0x8C is binary on the NOAH, only 0x8B is text
    return {"dhcp_lease": data.params.get(p.P_DHCP_LEASE_0)}


SENSORS = [
    NoahSensorDescription(key="mqtt_server", value=_param(p.P_MQTT_URL)),
    NoahSensorDescription(
        key="mqtt_host", value=_param(p.P_MQTT_HOST), entity_category=EntityCategory.DIAGNOSTIC
    ),
    NoahSensorDescription(key="mqtt_port", value=_param(p.P_MQTT_PORT)),
    NoahSensorDescription(key="firmware", value=_param(p.P_FIRMWARE), entity_category=EntityCategory.DIAGNOSTIC),
    NoahSensorDescription(
        key="mac",
        value=_param(p.P_MAC),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    NoahSensorDescription(
        key="wifi_signal",
        value=_int_param(p.P_WIFI_SIGNAL),
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    NoahSensorDescription(key="wifi_ssid", value=_param(p.P_WIFI_SSID), entity_category=EntityCategory.DIAGNOSTIC),
    NoahSensorDescription(
        key="ip_address", value=_ip_address, attributes=_dhcp_lease, entity_category=EntityCategory.DIAGNOSTIC
    ),
    NoahSensorDescription(key="device_type", value=_device_type, entity_category=EntityCategory.DIAGNOSTIC),
    NoahSensorDescription(
        key="model_id",
        value=_param(p.P_MODEL_ID),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    NoahSensorDescription(
        key="hw_version",
        value=_param(p.P_HW_VERSION),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    NoahSensorDescription(
        key="sdk_version",
        value=_param(p.P_SDK_VERSION),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    NoahSensorDescription(
        key="data_interval",
        value=_int_param(p.P_DATA_INTERVAL),
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # may hold a token of the Growatt account, so it is not recorded unless enabled
    NoahSensorDescription(
        key="auth_key",
        value=_param(p.P_AUTH_KEY),
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

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes is None:
            return None
        return self.entity_description.attributes(self.coordinator.data)
