#!/usr/bin/env python3
"""Command line tool for the Growatt NOAH BLE protocol: decode btsnoop logs, read and set parameters.

The protocol itself lives in custom_components/growatt_noah_ble/protocol.py.
"""
import argparse
import asyncio
from datetime import datetime
import os
import re
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_components", "growatt_noah_ble"))
import protocol as p  # noqa: E402


def btsnoop_att_values(path, handle=0x2A):
    """Yield (timestamp_us, value) for ATT writes/notifications to the given handle."""
    raw = open(path, "rb").read()
    if raw[:8] != b"btsnoop\0":
        raise ValueError("not a btsnoop file")
    off, bufs = 16, {}
    while off + 24 <= len(raw):
        _, incl, flags, _, ts = struct.unpack(">IIIIq", raw[off : off + 24])
        pkt = raw[off + 24 : off + 24 + incl]
        off += 24 + incl
        if not pkt or pkt[0] != 2:  # HCI ACL only
            continue
        hdr, n = struct.unpack("<HH", pkt[1:5])
        key = (hdr & 0xFFF, flags & 1)
        frag = pkt[5 : 5 + n]
        if (hdr >> 12) & 3 in (0, 2):
            l2len, cid = struct.unpack("<HH", frag[:4])
            bufs[key] = [l2len, cid, bytearray(frag[4:])]
        elif key in bufs:
            bufs[key][2] += frag
        else:
            continue
        l2len, cid, buf = bufs[key]
        if len(buf) < l2len:
            continue
        del bufs[key]
        if cid == 4 and buf[0] in (0x12, 0x52, 0x1B, 0x1D) and struct.unpack("<H", buf[1:3])[0] == handle:
            yield ts, bytes(buf[3:l2len])


class NoahBle:
    def __init__(self, address, verbose=False):
        from bleak import BleakClient

        self.client = BleakClient(address)
        self.rx = asyncio.Queue()
        self.verbose = verbose

    async def __aenter__(self):
        await self.client.connect()
        await self.client.start_notify(p.CHAR_UUID, lambda _, d: self.rx.put_nowait(bytes(d)))
        if p.parse_set_reply(await self.request(p.auth_request())) != 0:
            raise RuntimeError("authentication rejected")
        return self

    async def __aexit__(self, *exc):
        try:
            await self.client.disconnect()
        except EOFError:
            pass  # bleak/dbus_fast on Python 3.14 sometimes loses the D-Bus connection here; the link is gone anyway

    async def request(self, frame, timeout=10):
        if self.verbose:
            print(f"  tx {frame.hex()}")
        await self.client.write_gatt_char(p.CHAR_UUID, frame, response=True)
        buf = b""
        while True:  # notifications may be split if the MTU is small
            chunk = await asyncio.wait_for(self.rx.get(), timeout)
            if self.verbose:
                print(f"  rx {chunk.hex()}")
            frames, buf = p.extract_frames(buf + chunk)
            if not frames:
                continue
            proto, _, func, data = p.parse_frame(frames[0])
            print(p.describe(proto, func, data, redact=False))
            return data

    async def set_params(self, params):
        status = p.parse_set_reply(await self.request(p.set_request(params)))
        if status != 0:
            raise RuntimeError(f"device rejected set, status={status}")

    async def query(self, ids):
        return p.parse_query_reply(await self.request(p.query_request(ids)))[1]


def format_value(value):
    if all(0x20 <= b < 0x7F for b in value):
        return value.decode()
    return f"hex:{value.hex()}"


async def scan():
    from bleak import BleakScanner

    for dev, adv in (await BleakScanner.discover(timeout=8, return_adv=True)).values():
        mark = "*" if p.is_growatt_ble(adv.service_uuids, adv.manufacturer_data) else " "
        print(f"{mark} {dev.address}  rssi={adv.rssi:4}  {dev.name}")


async def run_client(args):
    async with NoahBle(args.address, args.verbose) as noah:
        params = []
        if args.ssid:
            params += [(p.P_WIFI_SSID, args.ssid), (p.P_WIFI_PASSWORD, args.password or "")]
        if args.host:
            params.append((p.P_MQTT_HOST, args.host))
        if args.port:
            params.append((p.P_MQTT_PORT, str(args.port)))
        if params:
            await noah.set_params(params)
        await noah.query([p.P_SERIAL, p.P_MAC, p.P_DEVICE_TYPE, p.P_FIRMWARE])
        await noah.query([p.P_MODEL_ID, p.P_HW_VERSION, p.P_SDK_VERSION])
        await noah.query([p.P_MQTT_URL, p.P_MQTT_HOST, p.P_MQTT_PORT])
        await noah.query([p.P_WIFI_STATUS, p.P_CONNECTION_STATE, p.P_WIFI_SIGNAL])
        await noah.query([p.P_DHCP_LEASE_0, p.P_DHCP_LEASE_1, p.P_AUTH_KEY])
        await noah.query([p.P_DATETIME, p.P_DATA_INTERVAL, p.P_WIFI_SSID])
        if args.restart:
            await noah.client.write_gatt_char(p.CHAR_UUID, p.restart_request(), response=True)
            print("restart sent")


async def dump(args):
    """Read every parameter id and write them to a text file; the space is 0..145 according to heliobind."""
    values, missing, failed = {}, [], []
    async with NoahBle(args.address, args.verbose) as noah:
        ids = list(range(args.last + 1))
        for start in range(0, len(ids), args.batch):
            batch = ids[start : start + args.batch]
            try:
                status, reply = p.parse_query_reply(await noah.request(p.query_request(batch)))
            except (TimeoutError, p.ProtocolError) as e:
                print(f"query {batch} failed: {e!r}", file=sys.stderr)
                failed += batch
                continue
            if status != 0:
                print(f"query {batch} returned status {status}", file=sys.stderr)
            values.update(reply)
            missing += [i for i in batch if i not in reply]

    serial = values.get(p.P_SERIAL, b"").decode(errors="replace") or args.address.replace(":", "")
    model = p.model_name(values.get(p.P_DEVICE_TYPE, b"").decode(errors="replace"))
    path = args.output or f"{re.sub(r'[^A-Za-z0-9]+', '-', model)}_{serial}_{datetime.now():%Y%m%d-%H%M%S}.txt"
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(f"# {model} {args.address}, serial {serial}, read {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"# ids 0..{args.last}; contains the WLAN password and the Bluetooth key in plain text\n")
        for i in sorted(values):
            f.write(f"{i:3}  0x{i:02X}  {p.PARAM_NAMES.get(i, ''):18}  {format_value(values[i])}\n")
        f.write(f"# no value: {', '.join(map(str, missing)) or '-'}\n")
        f.write(f"# no reply: {', '.join(map(str, failed)) or '-'}\n")
    print(f"{len(values)} values written to {path} (contains the WLAN password)")


async def modbus(args):
    """Read Modbus registers via the 0x17 passthrough, to find out what the unit behind the datalogger answers."""
    function = p.MODBUS_READ_INPUT if args.input else p.MODBUS_READ_HOLDING
    async with NoahBle(args.address, args.verbose) as noah:
        for start in range(args.start, args.start + args.count, args.batch):
            count = min(args.batch, args.start + args.count - start)
            try:
                regs = p.parse_modbus_read_reply(await noah.request(p.modbus_read_request(function, start, count)))
            except (TimeoutError, p.ProtocolError) as e:
                print(f"{start}..{start + count - 1}: {e}")
                continue
            for i, r in enumerate(regs):
                print(f"{start + i:5}  0x{r:04x}  {r:5}  {bytes([r >> 8, r & 0xFF])!r}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("decode", help="decode a btsnoop_hci.log")
    a.add_argument("file")
    sub.add_parser("scan", help="list BLE devices (* = Growatt datalogger)")
    a = sub.add_parser("config", help="authenticate, optionally set wifi/mqtt, then read back settings")
    a.add_argument("address")
    a.add_argument("--host", help="MQTT server host")
    a.add_argument("--port", type=int, help="MQTT server port")
    a.add_argument("--ssid")
    a.add_argument("--password")
    a.add_argument("--restart", action="store_true", help="restart the datalogger at the end")
    a.add_argument("-v", "--verbose", action="store_true", help="print raw frames and notifications")
    a = sub.add_parser("dump", help="read all parameters and write them to a text file")
    a.add_argument("address")
    a.add_argument("-o", "--output", help="file name (default: <device type>_<serial>_<time>.txt)")
    a.add_argument("--last", type=int, default=145, help="highest parameter id to read (default: 145)")
    a.add_argument("--batch", type=int, default=4, help="parameters per query (default: 4, like the app)")
    a.add_argument("-v", "--verbose", action="store_true", help="print raw frames and notifications")
    a = sub.add_parser("modbus", help="read Modbus registers of the unit behind the datalogger (0x17 passthrough)")
    a.add_argument("address")
    a.add_argument("start", type=int)
    a.add_argument("count", type=int, nargs="?", default=1)
    a.add_argument("--input", action="store_true", help="input registers (function 0x04) instead of holding (0x03)")
    a.add_argument("--batch", type=int, default=1, help="registers per request (default: 1)")
    a.add_argument("-v", "--verbose", action="store_true", help="print raw frames and notifications")
    args = ap.parse_args()

    if args.cmd == "decode":
        t0 = None
        for ts, frame in btsnoop_att_values(args.file):
            t0 = t0 or ts
            try:
                proto, _, func, data = p.parse_frame(frame)
                print(f"{(ts - t0) / 1e6:8.3f}  {p.describe(proto, func, data, redact=False)}")
            except (p.ProtocolError, struct.error) as e:
                print(f"{(ts - t0) / 1e6:8.3f}  <{e}> {frame.hex()}", file=sys.stderr)
    elif args.cmd == "scan":
        asyncio.run(scan())
    elif args.cmd == "dump":
        asyncio.run(dump(args))
    elif args.cmd == "modbus":
        asyncio.run(modbus(args))
    else:
        asyncio.run(run_client(args))


if __name__ == "__main__":
    main()
