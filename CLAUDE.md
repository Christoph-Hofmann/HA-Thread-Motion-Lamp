# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Home Assistant custom integration (`matter_motion_lamp`) that automatically renames Matter device entities for Espressif MotionLamp devices (manufacturer ID 65521, model IDs 32768–32820). It has no build system or test suite — development is done by deploying to a live Home Assistant instance.

## Installation & Testing

Copy `custom_components/matter_motion_lamp/` into Home Assistant's `custom_components/` directory, then restart HA and add the integration via Settings → Devices & Services.

To enable debug logging, add to `configuration.yaml`:
```yaml
logger:
  default: warning
  logs:
    custom_components.matter_motion_lamp: debug
```

## Architecture

**`__init__.py`** — All runtime logic:
- `async_setup_entry()`: Sets up event listeners and runs the startup scan
- `async_startup()`: On HA start, iterates all registered devices and calls `check_and_rename_device()` on each
- `async_entity_registry_updated()`: Listens for `entity_registry_updated` events; handles newly added entities in real-time
- `check_and_rename_device()`: Matches a device against the Espressif/MotionLamp criteria (by manufacturer field, model field, and Matter identifier format), then renames matching entities using values from `entity_renames.json`

**`entity_renames.json`** — Maps old entity IDs to new entity IDs and display names. This is the only file to change when adding new rename rules.

**`config_flow.py`** — Minimal; no user input. Sets a unique ID to prevent duplicate entries. All configuration is hard-coded via constants.

**`const.py`** — Central constants: domain name, Espressif manufacturer ID, MotionLamp model name/ID range, and path to `entity_renames.json`.

## HA Integration Constraints

- `manifest.json` declares `"dependencies": ["matter"]` — the Matter integration must load first
- `"single_config_entry": true` in `__init__.py` prevents duplicate instances
- No external Python dependencies; uses only HA core APIs (`homeassistant.helpers.device_registry`, `entity_registry`, `event`)
- Minimum HA version: 2024.1.0
