"""Constants for Matter Motion Lamp."""

DOMAIN = "matter_motion_lamp"

# Fixed manufacturer ID for Espressif - this is a constant and cannot be changed
MANUFACTURER_ID = 65521

# Fixed model ID range for MotionLamp - these are constants and cannot be changed
MODEL_NAME = "MotionLamp"
MODEL_ID_MIN = 32768
MODEL_ID_MAX = 32820

# JSON file containing the list of entity renames
ENTITY_RENAMES_FILE = "entity_renames.json"

MATTER_SERVER_URL = "ws://homeassistant.local:5580/ws"

# Your device details
NODE_ID = 61
ENDPOINT_ID = 0
CLUSTER_ID = 51  # Basic Information Cluster
ATTRIBUTE_ID = 2  # UpTime Attribute

# Update interval in seconds
SCAN_INTERVAL = 300  # 5 minutes