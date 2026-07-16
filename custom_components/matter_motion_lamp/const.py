"""Constants for Matter Motion Lamp."""

DOMAIN = "matter_motion_lamp"

# Fixed manufacturer ID for Espressif - this is a constant and cannot be changed
MANUFACTURER_ID = 65521

# Supported model names and IDs
MODEL_NAMES = frozenset({"MotionLamp", "MotionLamp CCT"})
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

# Dimmable-variant model name — the only variant with the runtime Light Count
# feature (not "MotionLamp CCT"). Used to scope the master "All Lights" entity.
LIGHT_COUNT_MODEL_NAME = "MotionLamp"

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