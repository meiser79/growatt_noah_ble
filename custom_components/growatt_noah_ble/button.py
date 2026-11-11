from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NoahConfigEntry, NoahCoordinator
from .entity import NoahEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: NoahConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities(
        [
            NoahButton(c, "apply_mqtt", c.async_apply_mqtt),
            NoahButton(c, "reconnect_wifi", c.async_reconnect_wifi),
            NoahButton(c, "restart", c.async_restart, ButtonDeviceClass.RESTART),
            NoahButton(c, "refresh", c.async_request_refresh),
        ]
    )


class NoahButton(NoahEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: NoahCoordinator, key: str, action, device_class=None) -> None:
        super().__init__(coordinator, key)
        self._action = action
        self._attr_device_class = device_class

    @property
    def available(self) -> bool:
        # actions open their own BLE connection, so they work even if the last poll failed
        return True

    async def async_press(self) -> None:
        await self._action()
