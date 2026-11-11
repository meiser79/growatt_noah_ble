from __future__ import annotations

import json
from pathlib import Path

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo, format_mac
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import protocol as p
from .coordinator import NoahCoordinator

# entity ids are always derived from the English names, whatever language HA uses
_EN_NAMES = {
    key: entry["name"]
    for platform in json.loads((Path(__file__).parent / "translations" / "en.json").read_text())["entity"].values()
    for key, entry in platform.items()
}


class NoahEntity(CoordinatorEntity[NoahCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: NoahCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{format_mac(coordinator.address)}_{key}"
        params = coordinator.data.params if coordinator.data else {}
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            manufacturer="Growatt",
            model="NOAH 2000",
            name=coordinator.config_entry.title,
            serial_number=params.get(p.P_SERIAL),
            sw_version=params.get(p.P_FIRMWARE),
        )

    @property
    def suggested_object_id(self) -> str | None:
        return _EN_NAMES.get(self._attr_translation_key)
