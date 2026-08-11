#!/usr/bin/env python3
"""MotionLamp OTA Bridge.

Pulls new MotionLamp firmware from the update server into the Matter Server
add-on's real OTA provider directory, and restarts Matter Server when new
firmware was actually delivered.

Why this add-on exists: the Matter Server add-on's --ota-provider-dir points
at /config/updates *inside its own container*, which is its own private
"app_config" storage (declared via `map: - type: app_config` in its
config.yaml) -- not Home Assistant Core's shared /config. A HA
custom_component (running inside HA Core, a separate container) has no way
to reach another add-on's private storage; that isolation is intentional.
This add-on solves it the way HAOS actually supports: declaring
`all_app_configs` in its own map grants host-level access to every app's
config directory under /app_configs/<slug>/, including Matter Server's.
"""
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("ota_bridge")

OPTIONS_PATH = Path("/data/options.json")
STATE_PATH = Path("/data/pushed_versions.json")
APP_CONFIGS_ROOT = Path("/app_configs")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN")


def load_options() -> dict:
    with OPTIONS_PATH.open() as f:
        return json.load(f)


def load_state() -> set:
    if STATE_PATH.exists():
        try:
            return set(json.loads(STATE_PATH.read_text()))
        except (json.JSONDecodeError, OSError):
            log.warning("Could not read %s, starting with empty state", STATE_PATH)
    return set()


def save_state(pushed: set) -> None:
    try:
        STATE_PATH.write_text(json.dumps(sorted(pushed)))
    except OSError as e:
        log.error("Failed to save state to %s: %s", STATE_PATH, e)


def fetch_index(update_server_url: str) -> list[str]:
    try:
        with urllib.request.urlopen(update_server_url, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as e:
        log.error("Failed to fetch update index from %s: %s", update_server_url, e)
        return []
    return re.findall(r'href="([^"]+\.(?:json|ota))"', body)


def download(update_server_url: str, filename: str, dest: Path) -> bool:
    url = update_server_url.rstrip("/") + "/" + filename
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            content = resp.read()
    except (urllib.error.URLError, OSError) as e:
        log.error("Failed to download %s: %s", url, e)
        return False
    try:
        dest.write_bytes(content)
    except OSError as e:
        log.error("Failed to write %s: %s", dest, e)
        return False
    log.info("Saved %s (%d bytes) -> %s", filename, len(content), dest)
    return True


def restart_matter_server(slug: str) -> None:
    if not SUPERVISOR_TOKEN:
        log.error("No SUPERVISOR_TOKEN available, cannot restart %s", slug)
        return
    req = urllib.request.Request(
        f"http://supervisor/addons/{slug}/restart",
        method="POST",
        headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"},
    )
    # Supervisor doesn't respond until the whole stop/cleanup/start cycle
    # finishes, which can comfortably exceed a normal HTTP timeout — a
    # client-side timeout here doesn't mean the restart failed, just that
    # we stopped waiting for its confirmation.
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            log.info("Restart requested for %s (status %s)", slug, resp.status)
    except TimeoutError:
        log.warning(
            "Restart request for %s timed out waiting for a response; "
            "the restart itself may still have completed.", slug,
        )
    except (urllib.error.URLError, OSError) as e:
        log.error("Failed to restart %s: %s", slug, e)


def run_check(options: dict) -> None:
    update_server_url = options["update_server_url"]
    matter_slug = options["matter_server_slug"]
    target_dir = APP_CONFIGS_ROOT / matter_slug / "updates"

    log.info("Checking %s for updates...", update_server_url)
    filenames = fetch_index(update_server_url)
    if not filenames:
        log.warning("No update files found at %s", update_server_url)
        return

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.error("Cannot create target directory %s: %s", target_dir, e)
        return

    pushed = load_state()
    new_ota_pushed = False

    for filename in filenames:
        name = Path(filename).name
        if name in pushed:
            continue
        dest = target_dir / name
        if not download(update_server_url, name, dest):
            continue
        pushed.add(name)
        if name.lower().endswith(".ota"):
            new_ota_pushed = True

    save_state(pushed)

    if new_ota_pushed:
        log.info("New firmware pushed - restarting %s", matter_slug)
        restart_matter_server(matter_slug)
    else:
        log.info("No new firmware found.")


def main() -> None:
    options = load_options()
    interval_hours = int(options.get("check_interval_hours", 12))

    log.info("MotionLamp OTA Bridge starting - checking every %dh", interval_hours)

    while True:
        try:
            run_check(options)
        except Exception:
            log.exception("Unexpected error during OTA check")
        time.sleep(interval_hours * 3600)


if __name__ == "__main__":
    main()
