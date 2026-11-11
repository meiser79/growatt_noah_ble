#!/usr/bin/env python3
"""Command line tool for the Growatt NOAH BLE protocol: decode btsnoop logs, read and set parameters.

The protocol itself lives in custom_components/growatt_noah_ble/protocol.py.
"""
import argparse
import asyncio
import os
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
            print(p.describe(proto, func, data))
            return data

    async def set_params(self, params):
        status = p.parse_set_reply(await self.request(p.set_request(params)))
        if status != 0:
            raise RuntimeError(f"device rejected set, status={status}")

    async def query(self, ids):
        return p.parse_query_reply(await self.request(p.query_request(ids)))[1]


async def scan():
    from bleak import BleakScanner

    for dev, adv in (await BleakScanner.discover(timeout=8, return_adv=True)).values():
        mark = "*" if p.SERVICE_UUID in adv.service_uuids else " "
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
        await noah.query([p.P_SERIAL, p.P_MAC, p.P_PARAM_13, p.P_FIRMWARE])
        await noah.query([p.P_MQTT_HOST_ACTIVE, p.P_MQTT_HOST, p.P_MQTT_PORT])
        await noah.query([p.P_WIFI_STATUS, p.P_CONNECTION_STATE])
        if args.restart:
            await noah.client.write_gatt_char(p.CHAR_UUID, p.restart_request(), response=True)
            print("restart sent")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("decode", help="decode a btsnoop_hci.log")
    a.add_argument("file")
    sub.add_parser("scan", help="list BLE devices (* = advertises the NOAH service)")
    a = sub.add_parser("config", help="authenticate, optionally set wifi/mqtt, then read back settings")
    a.add_argument("address")
    a.add_argument("--host", help="MQTT server host")
    a.add_argument("--port", type=int, help="MQTT server port")
    a.add_argument("--ssid")
    a.add_argument("--password")
    a.add_argument("--restart", action="store_true", help="restart the datalogger at the end")
    a.add_argument("-v", "--verbose", action="store_true", help="print raw frames and notifications")
    args = ap.parse_args()

    if args.cmd == "decode":
        t0 = None
        for ts, frame in btsnoop_att_values(args.file):
            t0 = t0 or ts
            try:
                proto, _, func, data = p.parse_frame(frame)
                print(f"{(ts - t0) / 1e6:8.3f}  {p.describe(proto, func, data)}")
            except (p.ProtocolError, struct.error) as e:
                print(f"{(ts - t0) / 1e6:8.3f}  <{e}> {frame.hex()}", file=sys.stderr)
    elif args.cmd == "scan":
        asyncio.run(scan())
    else:
        asyncio.run(run_client(args))


if __name__ == "__main__":
    main()
