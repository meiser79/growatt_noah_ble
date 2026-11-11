"""Short-lived BLE session with a NOAH: connect, authenticate, exchange frames, disconnect."""
from __future__ import annotations

import asyncio
import logging

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from . import protocol as p

_LOGGER = logging.getLogger(__name__)

REPLY_TIMEOUT = 15


class NoahError(Exception):
    """Communication with the NOAH failed."""


class NoahConnectError(NoahError):
    """No BLE connection could be established, e.g. adapter not ready yet after boot."""


class NoahClient:
    """Use as `async with NoahClient(ble_device) as noah:`."""

    def __init__(self, ble_device: BLEDevice) -> None:
        self._ble_device = ble_device
        self._client: BleakClientWithServiceCache | None = None
        self._frames: asyncio.Queue[bytes] = asyncio.Queue()
        self._buf = b""

    async def __aenter__(self) -> NoahClient:
        try:
            try:
                self._client = await establish_connection(
                    BleakClientWithServiceCache, self._ble_device, self._ble_device.name or self._ble_device.address
                )
            except (BleakError, TimeoutError) as err:
                raise NoahConnectError(f"connection failed: {err}") from err
            await self._client.start_notify(p.CHAR_UUID, self._on_notify)
            if p.parse_set_reply(await self._request(p.auth_request(), p.FUNC_SET)) != 0:
                raise NoahError("authentication rejected")
        except BaseException:
            await self._disconnect()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        await self._disconnect()

    async def _disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None

    def _on_notify(self, _sender, data: bytearray) -> None:
        # replies may be split over several notifications if the MTU is small
        _LOGGER.debug("rx %s", bytes(data).hex())
        frames, self._buf = p.extract_frames(self._buf + bytes(data))
        for frame in frames:
            self._frames.put_nowait(frame)

    async def _request(self, frame: bytes, func: int) -> bytes:
        assert self._client
        self._buf = b""
        while not self._frames.empty():
            self._frames.get_nowait()
        await self._client.write_gatt_char(p.CHAR_UUID, frame, response=True)
        while True:
            try:
                raw = await asyncio.wait_for(self._frames.get(), REPLY_TIMEOUT)
            except TimeoutError as err:
                raise NoahError(f"no reply to function 0x{func:02x}") from err
            try:
                proto, _, reply_func, data = p.parse_frame(raw)
            except p.ProtocolError as err:
                raise NoahError(str(err)) from err
            _LOGGER.debug("%s", p.describe(proto, reply_func, data))
            if reply_func == func:
                return data

    async def query(self, ids: list[int]) -> dict[int, str]:
        status, values = p.parse_query_reply(await self._request(p.query_request(ids), p.FUNC_QUERY))
        if status != 0:
            raise NoahError(f"query {ids} failed with status {status}")
        return {i: v.decode(errors="replace") for i, v in values.items()}

    async def set(self, params: list[tuple[int, str]]) -> None:
        status = p.parse_set_reply(await self._request(p.set_request(params), p.FUNC_SET))
        if status != 0:
            raise NoahError(f"set {[i for i, _ in params]} failed with status {status}")

    async def restart(self) -> None:
        """Restart the datalogger; it drops BLE and WLAN and reconnects."""
        assert self._client
        # the logger may reboot before it answers, so don't insist on a reply
        await self._client.write_gatt_char(p.CHAR_UUID, p.restart_request(), response=True)
        try:
            raw = await asyncio.wait_for(self._frames.get(), 5)
            _LOGGER.debug("restart reply: %s", raw.hex())
        except TimeoutError:
            pass
