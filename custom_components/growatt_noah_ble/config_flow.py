"""Config flow: pick the NOAH via Bluetooth, then the MQTT/WLAN settings to enforce."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import protocol as p
from .client import NoahClient, NoahError
from .const import (
    CONF_ENFORCE,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    CONF_SCAN_INTERVAL,
    CONF_WIFI_PASSWORD,
    CONF_WIFI_SSID,
    DEFAULT_MQTT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


def _settings_schema(defaults: dict[str, Any]) -> vol.Schema:
    def d(key, fallback=None):
        return {"suggested_value": defaults.get(key, fallback)}

    return vol.Schema(
        {
            vol.Optional(CONF_MQTT_HOST, description=d(CONF_MQTT_HOST)): str,
            vol.Required(CONF_MQTT_PORT, default=defaults.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)): NumberSelector(
                NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_WIFI_SSID, description=d(CONF_WIFI_SSID)): str,
            vol.Optional(CONF_WIFI_PASSWORD, description=d(CONF_WIFI_PASSWORD)): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_ENFORCE, default=defaults.get(CONF_ENFORCE, True)): bool,
            vol.Required(
                CONF_SCAN_INTERVAL, default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=1440, unit_of_measurement="min", mode=NumberSelectorMode.BOX)
            ),
        }
    )


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    out = dict(user_input)
    out[CONF_MQTT_PORT] = int(out[CONF_MQTT_PORT])
    out[CONF_SCAN_INTERVAL] = int(out[CONF_SCAN_INTERVAL])
    return out


def _looks_like_noah(info: BluetoothServiceInfoBleak) -> bool:
    return p.SERVICE_UUID in info.service_uuids


class NoahConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._name: str | None = None
        self._discovered: dict[str, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return NoahOptionsFlow()

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = discovery_info.name or discovery_info.address
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_settings()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            await self.async_set_unique_id(format_mac(address))
            self._abort_if_unique_id_configured()
            self._address = address
            self._name = self._discovered.get(address, address)
            return await self.async_step_settings()

        configured = {e.unique_id for e in self._async_current_entries()}
        self._discovered = {
            info.address: f"{info.name or '?'} ({info.address})"
            for info in async_discovered_service_info(self.hass, connectable=True)
            if _looks_like_noah(info) and format_mac(info.address) not in configured
        }
        # the NOAH might not advertise its service UUID, so a MAC can always be typed in
        schema = vol.Schema(
            {vol.Required(CONF_ADDRESS): vol.In(self._discovered) if self._discovered else str}
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            ble_device = async_ble_device_from_address(self.hass, self._address, connectable=True)
            if ble_device is None:
                errors["base"] = "not_in_range"
            else:
                try:
                    async with NoahClient(ble_device) as client:
                        serial = (await client.query([p.P_SERIAL])).get(p.P_SERIAL)
                except Exception:  # noqa: BLE001 - any failure means we could not talk to it
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title=f"NOAH {serial or self._name}",
                        data={CONF_ADDRESS: self._address},
                        options=_clean(user_input),
                    )

        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(user_input or {}),
            description_placeholders={"name": self._name},
            errors=errors,
        )


class NoahOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=_clean(user_input))
        return self.async_show_form(step_id="init", data_schema=_settings_schema(dict(self.config_entry.options)))
