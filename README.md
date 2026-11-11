# Growatt NOAH (Bluetooth) for Home Assistant

Custom integration that monitors and restores the network settings of a **Growatt NOAH 2000** over Bluetooth LE, without the ShinePhone app and without the Growatt cloud.

The NOAH occasionally forgets its MQTT server and falls back to `mqtt.growatt.com`, or it loses its WLAN connection. The integration polls it regularly over Bluetooth and writes the desired values back as soon as they differ.

The integration **only handles configuration**. It does not process the measurements the NOAH publishes via MQTT; use something like GroBro for that.

## Features

- **Enforce the MQTT server:** If the active MQTT server or port differs from the configured value, both are written again immediately.
- **Reconnect WLAN:** If the NOAH reports no network connection on two polls in a row, the WLAN name and password are sent again and the datalogger re-establishes the connection. The status is checked again 30 seconds later.
- **Poll on Bluetooth advertisement:** If the NOAH is unreachable, the integration polls as soon as it advertises again instead of waiting for the next interval. After a failed session it waits 5 minutes before the next attempt; if the connection could not be established at all (e.g. Bluetooth adapter still starting after a reboot), only 1 minute.
- **Short connections:** Each poll takes about 4 seconds; the connection is closed afterwards.
- **Bluetooth proxies:** Uses Home Assistant's Bluetooth stack, so it also works through ESPHome Bluetooth proxies.

## Requirements

- Home Assistant 2025.2 or newer
- A connectable Bluetooth adapter or ESPHome Bluetooth proxy within range of the NOAH
- No additional Python packages (`bleak`, `bleak-retry-connector` and `cryptography` ship with Home Assistant)

## Installation

### Manual

1. Copy the folder `custom_components/growatt_noah_ble` to `/config/custom_components/`.
2. Restart Home Assistant.

### HACS (custom repository)

1. HACS → menu → *Custom repositories* → `https://github.com/meiser79/growatt_noah_ble`, type *Integration*.
2. Install "Growatt NOAH (Bluetooth)" and restart Home Assistant.

## Setup

1. *Settings → Devices & services → Add integration → Growatt NOAH (Bluetooth)*.
   If the NOAH is detected, it also shows up directly as a discovered device.
2. Select the NOAH or enter its Bluetooth MAC address (see *Settings → Bluetooth → Advertisement monitor*).
3. Enter the settings:

| Option | Meaning |
|---|---|
| MQTT server | Server the NOAH should use. Leave empty to not manage the server. |
| MQTT port | Port of the MQTT server (default 8883) |
| WLAN name / WLAN password | Optional. Required for "Reconnect WLAN" and the automatic WLAN reconnect. |
| Restore settings automatically | Turns automatic correction of MQTT and WLAN on or off. |
| Poll interval | Minutes between two polls (default 10) |

During setup the integration connects to the NOAH once as a test. The options can be changed later via *Configure*.

## Entities

| Entity | Type | Description |
|---|---|---|
| Active MQTT server | Sensor | Server the NOAH is currently using |
| Stored MQTT server | Sensor (diagnostic) | Server stored in the NOAH |
| Stored MQTT port | Sensor (diagnostic) | Port stored in the NOAH |
| Firmware | Sensor (diagnostic) | Datalogger firmware |
| MAC address | Sensor (diagnostic, disabled) | WLAN MAC of the datalogger |
| Last Bluetooth contact | Sensor (diagnostic) | Time of the last successful poll |
| MQTT last restored | Sensor (diagnostic) | When the integration last corrected the MQTT server |
| WLAN last reconnected | Sensor (diagnostic) | When the WLAN credentials were last sent |
| Network | Binary sensor | On when the NOAH reports WLAN and server connection |
| Wrong MQTT server | Binary sensor (problem) | On when the active server differs from the configured one |
| Bluetooth reachable | Binary sensor (diagnostic) | Whether the last Bluetooth poll succeeded |
| Bluetooth polling | Switch | Off = Home Assistant no longer connects to the NOAH |
| Send MQTT settings | Button | Writes the MQTT server and port immediately |
| Reconnect WLAN | Button | Sends the WLAN name and password again, checks the status after 30 s |
| Restart datalogger | Button | Sends the restart command (see limitations) |
| Poll now | Button | Starts a poll immediately |

If the NOAH is unreachable, the sensors keep their last values. "Bluetooth reachable" and "Last Bluetooth contact" show whether the data is current.

"Network" is on when `0x37 = 0` and `0x3C` is one of `16`, `3` or `4`. This is the same success check the ShinePhone app uses during network setup.

### Example automation

```yaml
automation:
  - alias: NOAH forgot its MQTT server
    triggers:
      - trigger: state
        entity_id: sensor.noah_mqtt_last_restored
        not_to: [unknown, unavailable]
    actions:
      - action: notify.notify
        data:
          message: "The NOAH had forgotten its MQTT server and was reset."
```

The entity ID may differ on your system.

## Limitations and known issues

- **Only one Bluetooth connection at a time.** While Home Assistant is connected, nothing else can connect. Use the "Bluetooth polling" switch to pause the integration.
- **ShinePhone app: "bound by others".** The app's network setup (WLAN, then inverter selection) authenticates with the common device key like the integration does. At the end, after binding the NOAH to the plant in the Growatt cloud, it authenticates again with a fixed 32-character token belonging to the account. The NOAH rejects this token reproducibly: it either drops the Bluetooth connection right away or replies with status `1`. Usually the app shows no error, and the setup completes anyway. Once, the app was rejected with "The current device has been bound by others" while the integration kept working; whether that is related to the rejected token is unknown. The integration is not involved in the rejection; it happens within the app's own session. According to the app, resetting WLAN/Bluetooth on the NOAH resolves the error.
- **Restart command unconfirmed.** "Restart datalogger" sends parameter `0x20 = "1"`. The app uses this command for other Growatt devices; it is not confirmed that the NOAH handles it the same way.
- **Meaning of the status values.** The values of `0x37` and `0x3C` are only known from the app's success check, not fully documented.
- **Tested with one NOAH 2000 only** (datalogger firmware 4.0.2.6).

## Troubleshooting

Debug logging in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.growatt_noah_ble: debug
```

The log then shows every connection ("Connecting to NOAH …" / "Disconnected from NOAH …"), every received Bluetooth notification as raw `rx …`, and every command decrypted in plain text. When WLAN credentials are sent, the WLAN password appears in plain text in the log.

## Command line tool

`growatt_ble.py` uses the same protocol module and runs on any Linux machine with Bluetooth (`pip install bleak`):

```bash
# Scan for Bluetooth devices (* = advertises the NOAH service)
python3 growatt_ble.py scan

# Read settings
python3 growatt_ble.py config <MAC>

# Set the MQTT server, -v prints the raw frames
python3 growatt_ble.py config <MAC> --host mqtt.example.com --port 8883 -v

# Set WLAN
python3 growatt_ble.py config <MAC> --ssid "MyWLAN" --password "secret"

# Decrypt an Android btsnoop capture
python3 growatt_ble.py decode btsnoop_hci.log
```

Turn off the "Bluetooth polling" switch in Home Assistant first, otherwise the NOAH may be busy.

## Protocol

Derived from a Bluetooth capture and the ShinePhone app 8.5.9.2. Implemented in `custom_components/growatt_noah_ble/protocol.py`.

**GATT:** service `0x00FF`, characteristic `0xFF01` (write with response and notifications).

**Frame (big endian):**

```
totalLen u16 | protoVer u16 | dataLen u16 | addr u8 | func u8 | AES(data) | crc16 u16
```

| Field | Content |
|---|---|
| totalLen | Frame length without CRC |
| protoVer | `0x0006` app → device, `0x0007` device → app |
| dataLen | 2 + length of the data before padding |
| addr | always `0x01` |
| AES | AES-128-CBC, key `growatt_aes16key`, IV `growatt_aes16Ivs`; PKCS#7 padding, but no extra block if the data is already a multiple of 16 bytes |
| crc16 | CRC-16/MODBUS over everything before it |

The data always starts with the 10-character datalogger serial number (the app sends `0000000000`).

**Functions:**

| Code | Request | Reply |
|---|---|---|
| `0x18` set | `count u16, blockLen u16, {id u16, len u16, value}*` | `serial, count u16, status u8` (0 = ok) |
| `0x19` query | `count u16, id u16*` | `serial, count u16, status u8, {id u16, len u16, value}*` |
| `0x17` Modbus | `len u16, Modbus RTU frame incl. CRC` | same |

**Authentication:** The first command of every connection is `0x18` with parameter `0x36 = growatt_iot_device_common_key_01`.

Right after connecting, the NOAH sends the notification `00 01 02 … 0e` once or twice. It is not a frame and is skipped.

**Parameters (all values are ASCII text):**

| ID | Meaning |
|---|---|
| `0x08` | Serial number |
| `0x10` | MAC address |
| `0x11` | MQTT server |
| `0x12` | MQTT port |
| `0x13` | Active MQTT server (read only) |
| `0x15` | Firmware |
| `0x20` | Restart (`"1"`) |
| `0x36` | Authentication key |
| `0x37` | WLAN status (`0` = connected) |
| `0x38` | WLAN name |
| `0x39` | WLAN password |
| `0x3C` | Connection state (`16`, `3`, `4` = ok) |
| `0x4B` | WLAN scan (binary) |

**Modbus registers** (function `0x17`, Modbus address `0x01`), as used by the app during network setup:

| Register | Access | Meaning |
|---|---|---|
| `0x40`–`0x46` | read (`0x03`) | 14 ASCII characters, constant (`19211020213014` on the tested device); probably a version that the app passes on to the Growatt server |
| `300` (`0x012C`) | write (`0x10`) | Inverter bound to the NOAH (`ADDRESS_BIND_INVERTER_TO_NOAH` in the app), e.g. `0x0401` = APsystems EZ-1 |

The app fetches the list of inverter manufacturers and models, including the value for register `300`, from the Growatt server (`/noahDeviceApi/noah/getAssociatedInvManAndModelListByVersion`). For APsystems EZ-1, the 4th manufacturer and its 1st model, the value is `0x0401`; whether the high byte always is the manufacturer and the low byte the model is not confirmed.

## License

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for copyright and trademark notices.
