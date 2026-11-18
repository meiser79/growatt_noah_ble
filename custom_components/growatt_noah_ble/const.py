DOMAIN = "growatt_noah_ble"

CONF_MQTT_HOST = "mqtt_host"
CONF_MQTT_PORT = "mqtt_port"
CONF_WIFI_SSID = "wifi_ssid"
CONF_WIFI_PASSWORD = "wifi_password"
CONF_ENFORCE = "enforce"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_MQTT_PORT = 8883
DEFAULT_SCAN_INTERVAL = 10  # minutes

# number of polls in a row without network before the WLAN credentials are re-sent
OFFLINE_POLLS_BEFORE_RECONNECT = 2

# minimum seconds after a BLE session before an advertisement triggers a poll
WAKE_POLL_THROTTLE = 300
# shorter wait if the connection could not even be established
CONNECT_RETRY_DELAY = 60

# seconds after re-sending the WLAN credentials before the network status is checked
WIFI_CHECK_DELAY = 30
