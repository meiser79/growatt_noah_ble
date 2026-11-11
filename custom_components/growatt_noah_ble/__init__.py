"""Growatt NOAH 2000 configuration over Bluetooth LE."""
from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import NoahConfigEntry, NoahCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: NoahConfigEntry) -> bool:
    # no initial refresh: the first advertisement of the NOAH triggers a poll, after the
    # polling switch has restored its state
    coordinator = NoahCoordinator(hass, entry)
    entry.runtime_data = coordinator
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            coordinator.async_on_advertisement,
            bluetooth.BluetoothCallbackMatcher(address=coordinator.address, connectable=True),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NoahConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: NoahConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
