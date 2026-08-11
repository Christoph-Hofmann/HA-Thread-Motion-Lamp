# MotionLamp OTA Bridge

Delivers MotionLamp firmware updates to the Matter Server add-on, automatically.

## Why this exists

Home Assistant's Matter Server add-on looks for custom OTA firmware files in
its own private storage directory — one that a regular Home Assistant
integration (like [Matter Motion Lamp](../custom_components/matter_motion_lamp))
has no way to write into. That's intentional sandboxing on HAOS's part, not a
bug, but it means firmware pushed from the "Fetch Updates" button in the
integration never actually reaches Matter Server.

This add-on bridges that gap the way HAOS supports: add-ons (unlike
integrations) can declare access to every other add-on's private config
storage. This one uses that access for exactly one purpose — checking your
update server on a schedule, copying any new `.ota`/`.json` files into Matter
Server's real provider directory, and restarting Matter Server so it picks
them up.

## What it does

- On startup, and every `check_interval_hours` (default 12h): fetches the
  file listing from `update_server_url`.
- Downloads any file it hasn't already pushed before.
- If a new `.ota` file was pushed, restarts the Matter Server add-on so it
  imports it.
- Remembers what it's already pushed (`/data/pushed_versions.json`, private
  to this add-on) so it doesn't re-download or restart unnecessarily.

## Configuration

| Option | Description |
|---|---|
| `update_server_url` | Base URL of your firmware update server (must serve an HTML index with `.ota`/`.json` links, e.g. an Apache/nginx directory listing). |
| `matter_server_slug` | Slug of the Matter Server add-on. Leave as `core_matter_server` unless you've renamed or forked it. |
| `check_interval_hours` | How often to check for new firmware, in hours. |

## Requirements

- The official Matter Server add-on, installed and running.
- A firmware update server reachable from your Home Assistant host, serving
  `.ota` files built by this project's `build.sh ota` (see the main repo
  README).
