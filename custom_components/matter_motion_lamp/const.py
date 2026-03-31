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
UPDATE_TARGET_DIR = "/addon_configs/core_matter_server/updates"

MATTER_SERVER_URL = "ws://homeassistant.local:5580/ws"

ENDPOINT_ID = 0
CLUSTER_ID = 51  # Basic Information Cluster
ATTRIBUTE_ID = 2  # UpTime Attribute

# Update interval in seconds
SCAN_INTERVAL = 300  # 5 minutes