"""Growatt NOAH 2000 / ShineWiFi BLE protocol (reverse engineered from ShinePhone 8.5.9.2).

Frame (big endian):
    totalLen u16 | protoVer u16 | dataLen u16 | addr u8 | func u8 | AES(data) | crc16 u16

    totalLen  = length of the frame without the CRC
    protoVer  = 0x0006 app->device, 0x0007 device->app
    dataLen   = 2 (addr+func) + len(data) before padding
    AES       = AES-128-CBC, key "growatt_aes16key", iv "growatt_aes16Ivs",
                PKCS#7 padding but none if data is already a multiple of 16
    crc16     = CRC-16/MODBUS over everything before it

data always starts with the 10 byte datalogger serial ("0000000000" from the app).

func 0x18 (set):   count u16 | blockLen u16 | {id u16, len u16, value}*
       reply:      serial | count u16 | status u8 (0 = ok)
func 0x19 (query): count u16 | id u16 *
       reply:      serial | count u16 | status u8 | {id u16, len u16, value}*
func 0x17 (modbus passthrough): len u16 | modbus RTU frame incl. CRC

GATT: service 0x00FF, characteristic 0xFF01 (write + notify).

This module has no Home Assistant or bleak dependency so the CLI can share it.
"""
from __future__ import annotations

import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY = b"growatt_aes16key"
IV = b"growatt_aes16Ivs"
AUTH_KEY = b"growatt_iot_device_common_key_01"
APP_SERIAL = b"0000000000"

SERVICE_UUID = "000000ff-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
# The manufacturer data is ASCII "G:<device type>#<serial prefix>#..", e.g. "G:61#0PVP#0#0" for a NOAH 2000.
# The NOAH also sends it as "g:..", meaning unknown. Read as a little endian company id, "G:" is
# 0x3A47 and "g:" 0x3A67. Neither is enough on its own: the service UUID 0x00FF comes from Espressif's GATT
# example and is advertised by unrelated ESP32 devices too, and other Growatt devices send "g:" without it.
MANUFACTURER_IDS = (0x3A47, 0x3A67)


def is_growatt_ble(service_uuids, manufacturer_data) -> bool:
    """Whether an advertisement comes from a datalogger speaking this protocol."""
    return SERVICE_UUID in service_uuids and any(i in manufacturer_data for i in MANUFACTURER_IDS)

PROTO_APP = 6
PROTO_DEVICE = 7

FUNC_PASSTHROUGH = 0x17
FUNC_SET = 0x18
FUNC_QUERY = 0x19

P_SERIAL = 0x08
P_DEVICE_TYPE = 0x0D
P_MAC = 0x10
# 0x11 and 0x13 are one setting under two ids: writing either changes what both read back
P_MQTT_HOST = 0x11
P_MQTT_PORT = 0x12
P_MQTT_URL = 0x13
P_MODEL_ID = 0x14
P_FIRMWARE = 0x15
P_HW_VERSION = 0x16
P_RESTART = 0x20
# written to authenticate; read, it returns the key the logger stores besides the common key
P_AUTH_KEY = 0x36
P_WIFI_STATUS = 0x37
P_WIFI_SSID = 0x38
P_WIFI_PASSWORD = 0x39
P_CONNECTION_STATE = 0x3C
P_SDK_VERSION = 0x3D
P_WIFI_SCAN = 0x4B
P_WIFI_SIGNAL = 0x4C
P_DHCP_LEASE_0 = 0x8B
P_DHCP_LEASE_1 = 0x8C

PARAM_NAMES = {
    P_SERIAL: "serial",
    P_DEVICE_TYPE: "device_type",
    P_MAC: "mac",
    P_MQTT_HOST: "mqtt_host",
    P_MQTT_PORT: "mqtt_port",
    P_MQTT_URL: "mqtt_url",
    P_MODEL_ID: "model_id",
    P_FIRMWARE: "firmware",
    P_HW_VERSION: "hw_version",
    P_RESTART: "restart",
    P_AUTH_KEY: "auth_key",
    P_WIFI_STATUS: "wifi_status",
    P_WIFI_SSID: "wifi_ssid",
    P_WIFI_PASSWORD: "wifi_password",
    P_CONNECTION_STATE: "connection_state",
    P_SDK_VERSION: "sdk_version",
    P_WIFI_SCAN: "wifi_scan",
    P_WIFI_SIGNAL: "wifi_signal",
    P_DHCP_LEASE_0: "dhcp_lease_0",
    P_DHCP_LEASE_1: "dhcp_lease_1",
}

# value of P_DEVICE_TYPE, also sent in the advertisement ("G:61#...")
DEVICE_TYPES = {"61": "NOAH 2000", "66": "GroPlug", "72": "NEXA 2000", "73": "AURA/NODE 5000", "83": "VETA 2200"}


def model_name(device_type: str | None) -> str:
    return DEVICE_TYPES.get(device_type, "Unknown")

# SetUpNetProgressActivity treats the network setup as successful with these values
WIFI_STATUS_OK = "0"
CONNECTION_STATES_OK = ("16", "3", "4")


class ProtocolError(Exception):
    """Malformed or unexpected frame."""


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def aes_encrypt(data: bytes) -> bytes:
    # PKCS#7, except that block-aligned data gets no extra padding block
    pad = -len(data) % 16
    data += bytes([pad]) * pad
    enc = Cipher(algorithms.AES(KEY), modes.CBC(IV)).encryptor()
    return enc.update(data) + enc.finalize()


def aes_decrypt(data: bytes) -> bytes:
    dec = Cipher(algorithms.AES(KEY), modes.CBC(IV)).decryptor()
    return dec.update(data) + dec.finalize()


def build_frame(func: int, data: bytes, addr: int = 1, proto: int = PROTO_APP) -> bytes:
    enc = aes_encrypt(data)
    body = struct.pack(">HHHBB", 8 + len(enc), proto, 2 + len(data), addr, func) + enc
    return body + struct.pack(">H", crc16_modbus(body))


def frame_length(buf: bytes) -> int | None:
    """Total length incl. CRC of the frame starting at buf, or None if unknown yet."""
    if len(buf) < 2:
        return None
    return struct.unpack(">H", buf[:2])[0] + 2


MIN_FRAME = 8 + 16 + 2
MAX_FRAME = 4096


def extract_frames(buf: bytes) -> tuple[list[bytes], bytes]:
    """Split received notification bytes into complete device frames.

    Returns (frames, remaining bytes). Anything that is not a frame with protoVer 0x0007,
    a plausible length and a valid CRC is skipped: the NOAH notifies 00 01 02 .. 0e when
    notifications are switched on.
    """
    frames = []
    while len(buf) >= 4:
        n = frame_length(buf)
        if buf[2:4] != b"\x00\x07" or not MIN_FRAME <= n <= MAX_FRAME:
            buf = buf[1:]
            continue
        if len(buf) < n:
            break
        if crc16_modbus(buf[: n - 2]) != struct.unpack(">H", buf[n - 2 : n])[0]:
            buf = buf[1:]
            continue
        frames.append(buf[:n])
        buf = buf[n:]
    return frames, buf


def parse_frame(frame: bytes) -> tuple[int, int, int, bytes]:
    """Return (proto, addr, func, plaintext data)."""
    if len(frame) < 10 or crc16_modbus(frame[:-2]) != struct.unpack(">H", frame[-2:])[0]:
        raise ProtocolError("CRC mismatch")
    total, proto, data_len, addr, func = struct.unpack(">HHHBB", frame[:8])
    enc = frame[8:total]
    if len(enc) % 16:
        raise ProtocolError("encrypted part is not block aligned")
    return proto, addr, func, aes_decrypt(enc)[: data_len - 2]


def tlv(param_id: int, value: bytes | str) -> bytes:
    if isinstance(value, str):
        value = value.encode()
    return struct.pack(">HH", param_id, len(value)) + value


def parse_tlvs(buf: bytes) -> list[tuple[int, bytes]]:
    out = []
    while len(buf) >= 4:
        param_id, n = struct.unpack(">HH", buf[:4])
        out.append((param_id, buf[4 : 4 + n]))
        buf = buf[4 + n :]
    return out


def set_request(params: list[tuple[int, bytes | str]]) -> bytes:
    block = b"".join(tlv(i, v) for i, v in params)
    return build_frame(FUNC_SET, APP_SERIAL + struct.pack(">HH", len(params), len(block)) + block)


def query_request(ids: list[int]) -> bytes:
    return build_frame(
        FUNC_QUERY, APP_SERIAL + struct.pack(">H", len(ids)) + b"".join(struct.pack(">H", i) for i in ids)
    )


def auth_request() -> bytes:
    return set_request([(P_AUTH_KEY, AUTH_KEY)])


def restart_request() -> bytes:
    return set_request([(P_RESTART, "1")])


MODBUS_READ_HOLDING = 0x03
MODBUS_READ_INPUT = 0x04



def modbus_read_request(function: int, start: int, count: int) -> bytes:
    """0x17 passthrough of a Modbus RTU read to unit 1; the inner CRC is little endian as usual for Modbus."""
    pdu = struct.pack(">BBHH", 1, function, start, count)
    pdu += struct.pack("<H", crc16_modbus(pdu))
    return build_frame(FUNC_PASSTHROUGH, APP_SERIAL + struct.pack(">H", len(pdu)) + pdu)


def parse_modbus_read_reply(data: bytes) -> list[int]:
    """Return the register values of a 0x17 reply to a Modbus read."""
    if len(data) < 12:
        raise ProtocolError("short Modbus reply")
    n = struct.unpack(">H", data[10:12])[0]
    pdu = data[12 : 12 + n]
    if not pdu:
        raise ProtocolError("empty reply, the unit behind the datalogger did not answer")
    if len(pdu) < 5 or crc16_modbus(pdu[:-2]) != struct.unpack("<H", pdu[-2:])[0]:
        raise ProtocolError(f"bad Modbus reply {pdu.hex()}")
    if pdu[1] & 0x80:
        raise ProtocolError(f"Modbus exception {pdu[2]}")
    size = pdu[2]
    if size % 2 or 3 + size + 2 != len(pdu):
        raise ProtocolError(f"bad Modbus reply {pdu.hex()}")
    return list(struct.unpack(f">{size // 2}H", pdu[3 : 3 + size]))



def parse_set_reply(data: bytes) -> int:
    """Return the status byte of a 0x18 reply (0 = ok)."""
    if len(data) < 13:
        raise ProtocolError("short set reply")
    return data[12]


def parse_query_reply(data: bytes) -> tuple[int, dict[int, bytes]]:
    """Return (status, {param id: raw value}) of a 0x19 reply."""
    if len(data) < 13:
        raise ProtocolError("short query reply")
    return data[12], dict(parse_tlvs(data[13:]))


# values not to be logged; the common key is public and stays readable
SECRET_PARAMS = (P_AUTH_KEY, P_WIFI_PASSWORD)


def _item(param_id: int, value: bytes, redact: bool) -> str:
    name = PARAM_NAMES.get(param_id, hex(param_id))
    if redact and param_id in SECRET_PARAMS and value != AUTH_KEY:
        return f"{name}=<{len(value)} bytes redacted>"
    return f"{name}={value!r}"


def describe(proto: int, func: int, data: bytes, redact: bool = True) -> str:
    serial = data[:10].decode(errors="replace")
    rest = data[10:]
    d = "app->dev" if proto == PROTO_APP else "dev->app"
    if func == FUNC_SET and proto == PROTO_APP:
        count = struct.unpack(">H", rest[:2])[0]
        items = ", ".join(_item(i, v, redact) for i, v in parse_tlvs(rest[4:]))
        return f"{d} SET [{count}] {items}"
    if func == FUNC_SET:
        count, status = struct.unpack(">HB", rest[:3])
        return f"{d} SET-ACK sn={serial} count={count} status={status}"
    if func == FUNC_QUERY and proto == PROTO_APP:
        count = struct.unpack(">H", rest[:2])[0]
        ids = struct.unpack(f">{count}H", rest[2 : 2 + 2 * count])
        return f"{d} QUERY " + ", ".join(PARAM_NAMES.get(i, hex(i)) for i in ids)
    if func == FUNC_QUERY:
        status, values = parse_query_reply(data)
        items = ", ".join(_item(i, v, redact) for i, v in values.items())
        return f"{d} QUERY-RSP sn={serial} status={status} {items}"
    if func == FUNC_PASSTHROUGH:
        n = struct.unpack(">H", rest[:2])[0]
        return f"{d} MODBUS {rest[2:2 + n].hex()}"
    return f"{d} func=0x{func:02x} {data.hex()}"
