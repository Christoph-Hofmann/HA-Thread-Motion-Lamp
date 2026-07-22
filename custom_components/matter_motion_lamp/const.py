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

# Dimmable-variant model names — the variants with the runtime Light Count
# feature (not "MotionLamp CCT"). Used to scope the master "All Lights" entity.
LIGHT_COUNT_MODEL_NAMES = frozenset({"MotionLamp", "MotionLamp Rotary"})

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

# WS2812 RGB strip variant only
WS2812_MODEL_NAME = "MotionLamp RGB"
LAMP_ENDPOINT_ID = 1  # the lamp is always endpoint 1 on this firmware
# Custom vendor-specific cluster (see LAMP_LEDCOUNT_CLUSTER_ID in
# main/app_priv.h, motionlampthread firmware repo) — a Manufacturer
# Extensible Identifier: (vendor_id << 16) | local_id = (0xFFF1 << 16) | 0xFC01.
# Read-only from HA: matter-server's write_attribute requires the cluster to
# be one of matter.js's compiled-in standard clusters (ClusterMap lookup in
# @matter-server/ws-controller's ControllerCommandHandler#writeAttribute),
# which a custom vendor cluster never is — confirmed from that package's
# source, not just an untested guess. Reading works fine (the read path
# addresses purely by numeric IDs, no schema needed).
LED_COUNT_CLUSTER_ID = 0xFFF1FC01
LED_COUNT_ATTRIBUTE_ID = 0x0000