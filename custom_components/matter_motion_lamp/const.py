"""Constants for Matter Motion Lamp."""

DOMAIN = "matter_motion_lamp"

# Fixed manufacturer ID for Espressif - this is a constant and cannot be changed
MANUFACTURER_ID = 65521

# Supported model names and IDs
MODEL_NAMES = frozenset({"MotionLamp", "MotionLamp CCT", "MotionLamp Rotary", "MotionLamp RGB"})
MODEL_ID_MIN = 32768
MODEL_ID_MAX = 32820
MODEL_IDS_EXTRA = frozenset({8009})

# JSON file containing the list of entity renames
ENTITY_RENAMES_FILE = "entity_renames.json"

# JSON file containing the list of identify effects
ACTIONS_FILE = "actions.json"

# Firmware/config update server
UPDATE_SERVER_URL = "http://commisioner.its-hofmann.lo:5000/updates/"
# Must match the Matter Server add-on's --ota-provider-dir exactly (confirmed
# via its startup command line in the add-on log) — that's the only directory
# it actually scans for local OTA manifests. /config/ is HA Core's own main
# config directory, so it's directly writable from this integration.
UPDATE_TARGET_DIR = "/config/updates"

MATTER_SERVER_URL = "ws://homeassistant.local:5580/ws"

# WS2812 strip variant — the only one with a physical LED count to configure.
WS2812_MODEL_NAME = "MotionLamp RGB"
WS2812_LED_COUNT_MIN = 1
WS2812_LED_COUNT_MAX = 101  # must match WS2812_STRIP_LED_COUNT in app_priv.h

# Lamp auto-off duration — OnOff::OnTime (cluster 6, attribute 0x4001) on the
# lamp's own endpoint (always endpoint 1, created first in app_main() before
# any optional/variable-position endpoints). Applies to every variant.
# Bounds must match POWER_ONTIME_MIN_S/POWER_ONTIME_MAX_S in app_priv.h.
LAMP_ONTIME_ENDPOINT_ID = 1
LAMP_ONTIME_CLUSTER_ID = 6
LAMP_ONTIME_ATTRIBUTE_ID = 16385
LAMP_ONTIME_MIN_S = 10
LAMP_ONTIME_MAX_S = 7200

# Effect (Blink/Flash/Channel Blink/Channel Flash) auto-stop duration —
# plain NVS-backed app state, no Matter attribute of its own (see
# EFFECT_TIMEOUT_NVS_NS in app_driver.cpp), so it's only reachable over the
# firmware's own HTTP REST API (GET /sensors, POST /config/effect_length) at
# the device's IPv6 address, not via Matter/matter-server. Bounds must match
# EFFECT_TIMEOUT_MIN_S/MAX_S in app_priv.h.
EFFECT_LENGTH_MIN_S = 1
EFFECT_LENGTH_MAX_S = 300

# Official "Matter Server" add-on slug (Home Assistant core add-ons repo).
# Used for the "Restart Matter Server" button, which calls the hassio
# integration's addon_restart service — only works on Supervised/HAOS
# installs where that add-on is actually installed under this slug.
MATTER_SERVER_ADDON_SLUG = "core_matter_server"

ENDPOINT_ID = 0
CLUSTER_ID = 51  # Basic Information Cluster
ATTRIBUTE_ID = 2  # UpTime Attribute

# Update interval in seconds
SCAN_INTERVAL = 300  # 5 minutes
