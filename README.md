# Matter Motion Lamp for Home Assistant

Automatically rename Matter device entities based on manufacturer and model IDs.

## Features

- Automatically detects Matter devices by manufacturer ID and model ID
- Renames switch entities to a custom entity ID
- Configurable via UI
- Works with Espressif Matter devices (manufacturer ID 65521 and model ID range 32768–32820 are fixed constants)
- Processes existing devices on startup
- Listens for new devices being added

## Installation

### HACS (Recommended)
1. Add this repository as a custom repository in HACS:
   - Go to HACS → Integrations → Three dots → Custom repositories
   - URL: `https://github.com/Christoph-Hofmann/HA-Thread-Motion-Lamp`
   - Category: Integration
2. Click "Install"

### Manual Installation
1. Copy the `matter_motion_lamp` folder to `custom_components/`
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Matter Motion Lamp"
3. Click **Submit** — no configuration needed. All values are fixed constants:
   - **Manufacturer ID**: `65521` (Espressif)
   - **Model ID range**: `32768–32820` (MotionLamp)
   - **Entity ID**: `switch.power_on_motion`
   - **Name**: `Power on Motion`

## How It Works

The integration:
- Monitors Home Assistant's device registry
- When a device with matching manufacturer/model IDs is found
- Automatically renames the switch entity to your desired entity ID

## Example

For a Matter MotionLamp device:
- Original: `switch.motionlamp_schalter_5_3`
- After rename: `switch.power_on_motion`

## Debugging

Add to `configuration.yaml`:
```yaml
logger:
  default: warning
  logs:
    custom_components.matter_motion_lamp: debug
