"""Polls the NOAH over BLE and re-applies MQTT/WLAN settings it has forgotten."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import time

from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import protocol as p
from .client import NoahClient, NoahConnectError, NoahError
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
    OFFLINE_POLLS_BEFORE_RECONNECT,
    CONNECT_RETRY_DELAY,
    WAKE_POLL_THROTTLE,
    WIFI_CHECK_DELAY,
)

_LOGGER = logging.getLogger(__name__)

# the app never asks for more than four parameters at once, so neither do we
INFO_IDS = [p.P_SERIAL, p.P_MAC, p.P_FIRMWARE]
MQTT_IDS = [p.P_MQTT_HOST_ACTIVE, p.P_MQTT_HOST, p.P_MQTT_PORT]
STATUS_IDS = [p.P_WIFI_STATUS, p.P_CONNECTION_STATE]

type NoahConfigEntry = ConfigEntry[NoahCoordinator]


@dataclass
class NoahData:
    params: dict[int, str] = field(default_factory=dict)
    mqtt_ok: bool | None = None
    network_ok: bool | None = None
    reachable: bool = False
    last_contact: datetime | None = None
    last_mqtt_fix: datetime | None = None
    last_wifi_fix: datetime | None = None


class NoahCoordinator(DataUpdateCoordinator[NoahData]):
    config_entry: NoahConfigEntry

    def __init__(self, hass: HomeAssistant, entry: NoahConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.address: str = entry.data[CONF_ADDRESS]
        self._lock = asyncio.Lock()
        self._offline_polls = 0
        self._next_wake_poll = 0.0
        self._state = NoahData()
        self.data = self._state
        # set by the "Bluetooth polling" switch so the ShinePhone app can connect
        self.polling_enabled = True
        self._unsub_wifi_check = None
        entry.async_on_unload(self._cancel_wifi_check)

    @property
    def _opts(self):
        return self.config_entry.options

    def _desired_mqtt(self) -> tuple[str, str] | None:
        host = self._opts.get(CONF_MQTT_HOST)
        if not host:
            return None
        return host, str(self._opts.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT))

    def _wifi_credentials(self) -> tuple[str, str] | None:
        ssid = self._opts.get(CONF_WIFI_SSID)
        if not ssid:
            return None
        return ssid, self._opts.get(CONF_WIFI_PASSWORD, "")

    async def _session(self, action):
        """Run `action(client)` in one BLE connection, serialised with all other sessions."""
        ble_device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if ble_device is None:
            raise NoahError(f"NOAH {self.address} is not in range of a connectable Bluetooth adapter or proxy")
        async with self._lock:
            self._next_wake_poll = time.monotonic() + WAKE_POLL_THROTTLE
            _LOGGER.debug("Connecting to NOAH %s", self.address)
            try:
                async with NoahClient(ble_device) as client:
                    return await action(client)
            except NoahConnectError:
                # nothing was connected, so retrying soon can't block anyone (e.g. adapter still starting after boot)
                self._next_wake_poll = time.monotonic() + CONNECT_RETRY_DELAY
                raise
            except (BleakError, TimeoutError) as err:
                raise NoahError(f"Bluetooth error: {err}") from err
            finally:
                _LOGGER.debug("Disconnected from NOAH %s", self.address)

    def _evaluate(self) -> None:
        params = self._state.params
        desired = self._desired_mqtt()
        self._state.mqtt_ok = desired is None or (
            params.get(p.P_MQTT_HOST_ACTIVE) == desired[0] and params.get(p.P_MQTT_PORT) == desired[1]
        )
        self._state.network_ok = p.P_WIFI_STATUS in params and (
            params.get(p.P_WIFI_STATUS) == p.WIFI_STATUS_OK
            and params.get(p.P_CONNECTION_STATE) in p.CONNECTION_STATES_OK
        )

    async def _poll(self, client: NoahClient) -> None:
        if p.P_SERIAL not in self._state.params:
            self._state.params.update(await client.query(INFO_IDS))
        self._state.params.update(await client.query(MQTT_IDS))
        self._state.params.update(await client.query(STATUS_IDS))
        self._evaluate()

        if not self._opts.get(CONF_ENFORCE, True):
            return

        if not self._state.mqtt_ok:
            _LOGGER.warning(
                "NOAH uses MQTT server %s:%s, restoring %s:%s",
                self._state.params.get(p.P_MQTT_HOST_ACTIVE),
                self._state.params.get(p.P_MQTT_PORT),
                *self._desired_mqtt(),
            )
            await self._apply_mqtt(client)

        self._offline_polls = 0 if self._state.network_ok else self._offline_polls + 1
        if self._offline_polls >= OFFLINE_POLLS_BEFORE_RECONNECT and self._wifi_credentials():
            _LOGGER.warning("NOAH has had no network for %s polls, re-sending WLAN credentials", self._offline_polls)
            self._offline_polls = 0
            await self._apply_wifi(client)

    async def _apply_mqtt(self, client: NoahClient) -> None:
        host, port = self._desired_mqtt()
        await client.set([(p.P_MQTT_HOST, host), (p.P_MQTT_PORT, port)])
        self._state.params.update(await client.query(MQTT_IDS))
        self._state.last_mqtt_fix = dt_util.utcnow()
        self._evaluate()

    async def _apply_wifi(self, client: NoahClient) -> None:
        # same as the app's network setup; the logger reconnects to the WLAN after this
        ssid, password = self._wifi_credentials()
        await client.set([(p.P_WIFI_SSID, ssid), (p.P_WIFI_PASSWORD, password)])
        self._state.last_wifi_fix = dt_util.utcnow()
        # the status is only meaningful once the logger had time to reconnect
        self._cancel_wifi_check()
        self._unsub_wifi_check = async_call_later(self.hass, WIFI_CHECK_DELAY, self._async_wifi_check)

    @callback
    def _cancel_wifi_check(self) -> None:
        if self._unsub_wifi_check:
            self._unsub_wifi_check()
            self._unsub_wifi_check = None

    async def _async_wifi_check(self, _now) -> None:
        self._unsub_wifi_check = None
        _LOGGER.debug("Checking network status of NOAH %s after re-sending WLAN credentials", self.address)
        await self.async_request_refresh()

    async def _async_update_data(self) -> NoahData:
        # The NOAH only advertises (and accepts connections) some of the time. An unreachable
        # NOAH is therefore normal: keep the last known values and report it via `reachable`.
        if not self.polling_enabled:
            return self._state
        try:
            await self._session(self._poll)
        except NoahError as err:
            if self._state.reachable or self._state.last_contact is None:
                _LOGGER.info("NOAH %s not reachable via Bluetooth: %s", self.address, err)
            self._state.reachable = False
        else:
            if not self._state.reachable:
                _LOGGER.info("NOAH %s reachable via Bluetooth again", self.address)
            self._state.reachable = True
            self._state.last_contact = dt_util.utcnow()
        return self._state

    @callback
    def async_on_advertisement(
        self, service_info: bluetooth.BluetoothServiceInfoBleak, change: bluetooth.BluetoothChange
    ) -> None:
        """Poll right away when an unreachable NOAH starts advertising, instead of waiting for the interval."""
        if not self.polling_enabled or self._state.reachable or self._lock.locked():
            return
        # also after failed sessions, so a NOAH that won't talk to us isn't hammered with connections
        if time.monotonic() < self._next_wake_poll:
            return
        _LOGGER.debug("NOAH %s advertises, polling now", self.address)
        self.config_entry.async_create_background_task(self.hass, self.async_refresh(), "growatt_noah_ble wake poll")

    async def _run_action(self, action) -> None:
        try:
            await self._session(action)
        except NoahError as err:
            self._state.reachable = False
            self.async_set_updated_data(self._state)
            raise HomeAssistantError(str(err)) from err
        self._state.reachable = True
        self._state.last_contact = dt_util.utcnow()
        self.async_set_updated_data(self._state)

    async def async_apply_mqtt(self) -> None:
        if not self._desired_mqtt():
            raise HomeAssistantError("No MQTT server configured")
        await self._run_action(self._apply_mqtt)

    async def async_reconnect_wifi(self) -> None:
        if not self._wifi_credentials():
            raise HomeAssistantError("No WLAN credentials configured")
        await self._run_action(self._apply_wifi)

    async def async_restart(self) -> None:
        await self._run_action(lambda client: client.restart())
