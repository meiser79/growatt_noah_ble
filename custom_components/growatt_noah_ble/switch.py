from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import NoahConfigEntry
from .entity import NoahEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: NoahConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([PollingSwitch(entry.runtime_data, "polling")])


class PollingSwitch(NoahEntity, SwitchEntity, RestoreEntity):
    """Off = leave the NOAH alone (no polls), e.g. so the ShinePhone app can connect."""

    _attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.coordinator.polling_enabled = last.state != STATE_OFF

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.polling_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.polling_enabled = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.polling_enabled = False
        self.async_write_ha_state()
