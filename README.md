# Growatt NOAH (Bluetooth) for Home Assistant

Custom integration that monitors and restores the network settings of a **Growatt NOAH 2000** over Bluetooth LE, without the ShinePhone app and without the Growatt cloud.

The NOAH occasionally forgets its MQTT server and falls back to `mqtt.growatt.com`, or it loses its WLAN connection. The integration polls it regularly over Bluetooth and writes the desired values back as soon as they differ.

The integration **only handles configuration**. It does not process the measurements the NOAH publishes via MQTT; use something like GroBro for that.

## Features

- **Enforce the MQTT server:** If the MQTT server or port differs from the configured value, both are written again immediately.
- **Reconnect WLAN:** If the NOAH reports no WLAN connection on two polls in a row, the WLAN name and password are sent again and the datalogger re-establishes the connection. The WLAN name is read back, and the status is checked again 30 seconds later. If only the MQTT server is unreachable, the WLAN credentials are not re-sent.
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
   If the NOAH is detected, it also shows up directly as a discovered device. It is recognised by the service UUID `0x00FF` together with the manufacturer data `G:61#…` or `g:61#…` (company ID `0x3A47` or `0x3A67`). The case of the letter is a state: `G` while the key stored in `0x36` differs from the common key, usually because the ShinePhone app bound the NOAH to an account, and `g` while it holds the common key. Neither condition is enough on its own: unrelated ESP32 devices advertise `0x00FF` too, and other Growatt devices send `g:` without it. Other Growatt dataloggers in range (NEXA, GroPlug, a neighbour's NOAH) can still show up; check the MAC before adding one.
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
| MQTT server | Sensor | Server the NOAH uses (`0x13`) |
| MQTT server (0x11) | Sensor (diagnostic) | The same setting read via `0x11`; always equal to "MQTT server" |
| MQTT port | Sensor | Port the NOAH uses |
| Firmware | Sensor (diagnostic) | Datalogger firmware |
| MAC address | Sensor (diagnostic, disabled) | WLAN MAC of the datalogger (the Bluetooth MAC is this + 2) |
| WLAN signal | Sensor (diagnostic) | WLAN signal strength in dBm |
| WLAN name | Sensor (diagnostic) | WLAN the NOAH is configured for |
| IP address | Sensor (diagnostic) | IP address from the DHCP lease (`0x8B`); the raw lease string is an attribute |
| Device type | Sensor (diagnostic) | Product from `0x0D`, e.g. NOAH 2000 (`61`) |
| Model ID, Hardware version, SDK version | Sensors (diagnostic, disabled) | Further version information |
| Data interval | Sensor (diagnostic) | How often the NOAH publishes its data via MQTT, in seconds (5 by default) |
| Bluetooth key | Sensor (diagnostic, disabled) | Key stored in `0x36`, see below |
| Last Bluetooth contact | Sensor (diagnostic) | Time of the last successful poll |
| MQTT last restored | Sensor (diagnostic) | When the integration last corrected the MQTT server |
| WLAN last reconnected | Sensor (diagnostic) | When the WLAN credentials were last sent |
| WLAN connection | Binary sensor | On when the NOAH is connected to the WLAN router |
| Server connection | Binary sensor | On when the NOAH is connected to its MQTT server |
| Wrong MQTT server | Binary sensor (problem) | On when the NOAH's server or port differs from the configured one |
| Bluetooth reachable | Binary sensor (diagnostic) | Whether the last Bluetooth poll succeeded |
| Bluetooth polling | Switch | Off = Home Assistant no longer connects to the NOAH |
| Send MQTT settings | Button | Writes the MQTT server and port immediately |
| Reconnect WLAN | Button | Sends the WLAN name and password again, checks the status after 30 s |
| Set clock | Button | Writes Home Assistant's local time to `0x1F` (see limitations) |
| Restart datalogger | Button | Sends the restart command (see limitations) |
| Poll now | Button | Starts a poll immediately |

If the NOAH is unreachable, the sensors keep their last values. "Bluetooth reachable" and "Last Bluetooth contact" show whether the data is current.

**At night the NOAH is usually unreachable, and that is normal.** It switches itself off completely when the battery is at its lower charge limit and there is no solar power, and it switches on again at first light; nothing can wake it in between. During that time it does not advertise, so "Bluetooth reachable" is off. The first poll after it wakes up corrects anything it lost. (The exact conditions are documented by [heliobridge](https://github.com/longsleep/heliobridge/blob/main/docs/sleep.md) for the NEXA 2000, which uses the same datalogger.)

"WLAN connection" is on when `0x37 = 0`, "Server connection" when `0x3C` is one of `16`, `3` or `4`. Together they are the success check the ShinePhone app uses during network setup.

"Bluetooth key" shows the key the datalogger stores in `0x36`. On a NOAH set up with the ShinePhone app this is a 32-character token of the Growatt account, which reportedly opens the Bluetooth interface of every device of that account. The datalogger accepts the common key in addition, so the integration does not need it. The entity is disabled by default; if you enable it, the token ends up in the recorder history and in backups.

To remove the token from the NOAH, hold its IoT button for 3 to 10 seconds: the datalogger writes the common key back into `0x36` and advertises `g:` again. This is not a factory reset and keeps the WLAN and server settings, but the datalogger restarts its network connection and is offline for about 11 seconds.

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
- **ShinePhone app: "bound by others".** The app's network setup (WLAN, then inverter selection) authenticates with the common device key like the integration does. At the end, after binding the NOAH to the plant in the Growatt cloud, it authenticates again with a fixed 32-character token belonging to the account. In the captures the NOAH rejected this token every time: it either dropped the Bluetooth connection right away or replied with status `1`, although the same token can be read from `0x36` later. Usually the app shows no error, and the setup completes anyway. Once, the app was rejected with "The current device has been bound by others" while the integration kept working; whether that is related to the rejected token is unknown. The integration is not involved in the rejection; it happens within the app's own session. According to the app, resetting WLAN/Bluetooth on the NOAH resolves the error.
- **Setting the clock unconfirmed.** "Set clock" writes the time to `0x1F`, as GroBro's "Sync Time" does. `0x1F` is not a running clock: reading it returns the last time written, unchanged, so it cannot show whether the NOAH's clock is right. The datalogger's own clock starts at 2020-01-01 on every boot (see the event log in `0x7C`–`0x8A`). Whether the datalogger passes the time on to the NOAH, and which clock its time slots run on, is not confirmed.
- **Restart command unconfirmed.** "Restart datalogger" sends parameter `0x20 = "1"`. The app uses this command for other Growatt devices; it is not confirmed that the NOAH handles it the same way.
- **Meaning of the status values.** `0x37` is the link to the WLAN router (`0` = connected) and `0x3C` the link to the MQTT server (`3`, `4` or `16` = connected). Other values are failure codes whose meaning is unknown.
- **Tested with one NOAH 2000 only** (datalogger firmware 4.0.2.6).

## Troubleshooting

Debug logging in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.growatt_noah_ble: debug
```

The log then shows every connection ("Connecting to NOAH …" / "Disconnected from NOAH …"), every received Bluetooth notification as raw `rx …`, and every command decrypted in plain text. The WLAN password and a Bluetooth key other than the common key are replaced by `<n bytes redacted>`. The command line tool shows them in plain text.

## Command line tool

`growatt_ble.py` uses the same protocol module and runs on any Linux machine with Bluetooth (`pip install bleak`):

```bash
# Scan for Bluetooth devices (* = Growatt datalogger)
python3 growatt_ble.py scan

# Read settings
python3 growatt_ble.py config <MAC>

# Set the MQTT server, -v prints the raw frames
python3 growatt_ble.py config <MAC> --host mqtt.example.com --port 8883 -v

# Set WLAN
python3 growatt_ble.py config <MAC> --ssid "MyWLAN" --password "secret"

# Read all parameters (ids 0..145) into <device type>_<serial>_<time>.txt, e.g. NOAH-2000_0PVPC0ED35PT00RU_20261118-110000.txt
# The file contains the WLAN password and the Bluetooth key in plain text; it is created with mode 600.
python3 growatt_ble.py dump <MAC>

# Read Modbus registers of the unit behind the datalogger (0x17 passthrough):
# holding registers 64..70, then input registers 0..108 in groups of 8
python3 growatt_ble.py modbus <MAC> 64 7 --batch 7
python3 growatt_ble.py modbus <MAC> 0 109 --input --batch 8

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

**Authentication:** The first command of every connection is `0x18` with parameter `0x36 = growatt_iot_device_common_key_01`. The datalogger also stores a device or account key in `0x36`, but it accepts the common key in addition to that one, so the common key works on devices set up with the ShinePhone app too.

Right after connecting, the NOAH sends the notification `00 01 02 … 0e` once or twice. It is not a frame and is skipped.

**Parameters (all values are ASCII text):**

| ID | Meaning |
|---|---|
| `0x04` | Data interval (seconds) |
| `0x08` | Serial number |
| `0x0D` | Device type (`61` = NOAH 2000, `66` GroPlug, `72` NEXA 2000, `73` AURA/NODE 5000, `83` VETA 2200) |
| `0x10` | WLAN MAC address (on the NOAH the real one; the NEXA reports a masked constant here, the NOAH in `0x35`) |
| `0x11` | MQTT server |
| `0x12` | MQTT port |
| `0x13` | MQTT server, the same setting as `0x11`: writing one changes what both read back |
| `0x14` | Model ID |
| `0x15` | Firmware |
| `0x16` | Hardware version |
| `0x1E` | Time zone (`GMT+8` on the tested device) |
| `0x1F` | Set the clock (`YYYY-MM-DD HH:MM:SS`, local time); reads back the last time written |
| `0x20` | Restart (`"1"`) |
| `0x36` | Authentication key (write); stored key (read) |
| `0x37` | Router status (`0` = connected) |
| `0x38` | WLAN name |
| `0x39` | WLAN password |
| `0x3C` | Server status (`16`, `3`, `4` = connected) |
| `0x3D` | ESP-IDF version |
| `0x4B` | WLAN scan (binary) |
| `0x4C` | WLAN signal (dBm) |
| `0x79` | Connection diagnostics as text; **contains the WLAN password in plain text** |
| `0x7C`–`0x8A` | Event log, one entry per parameter: `<code>,TIME:<datalogger clock> …-wifi:…,server:<host>,<port>,…` |
| `0x8B` | DHCP lease as text: `-<IP>-<netmask>-<gateway>--<DNS>-…` |
| `0x8C` | Second DHCP lease; binary on the NOAH |

The ShinePhone app writes the MQTT server (`0x11`) and port (`0x12`) in separate commands and never writes `0x13`; `0x13` follows `0x11` immediately.

**Modbus registers** (function `0x17`, Modbus address `0x01`), as used by the app during network setup:

| Register | Access | Meaning |
|---|---|---|
| `0x40`–`0x46` | read (`0x03`) | 14 ASCII characters, constant (`19211020213014` on the tested device); probably a version that the app passes on to the Growatt server, possibly `19` plus the build time `21-10-20 21:30:14` |
| `300` (`0x012C`) | write (`0x10`) | Inverter bound to the NOAH (`ADDRESS_BIND_INVERTER_TO_NOAH` in the app), e.g. `0x0401` = APsystems EZ-1 |

Input registers (function `0x04`) answer from `0` to `108`; from `109` on the NOAH returns an empty reply. So the firmware versions that GroBro reads from input registers 119/120 of the MQTT data cannot be read this way.

The app fetches the list of inverter manufacturers and models, including the value for register `300`, from the Growatt server (`/noahDeviceApi/noah/getAssociatedInvManAndModelListByVersion`). For APsystems EZ-1, the 4th manufacturer and its 1st model, the value is `0x0401`; whether the high byte always is the manufacturer and the low byte the model is not confirmed.

## License

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for copyright and trademark notices.
