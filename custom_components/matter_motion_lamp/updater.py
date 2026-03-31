"""Fetch JSON update files from the update server and write via Supervisor API."""

import logging
import os
import re
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import UPDATE_SERVER_URL, UPDATE_TARGET_DIR

_LOGGER = logging.getLogger(__name__)

_SUPERVISOR_API = "http://supervisor"


def _supervisor_headers() -> dict:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        _LOGGER.warning("SUPERVISOR_TOKEN not set — cannot write via Supervisor API")
    return {"Authorization": f"Bearer {token}"}


async def _supervisor_mkdir(session, rel_path: str) -> None:
    """Ensure directory exists via Supervisor FS API."""
    url = f"{_SUPERVISOR_API}/fs/mkdir/{rel_path}"
    try:
        async with session.post(url, headers=_supervisor_headers()) as resp:
            if resp.status in (200, 201, 409):
                _LOGGER.debug("Directory ready: /%s (status %s)", rel_path, resp.status)
            else:
                body = await resp.text()
                _LOGGER.warning("mkdir /%s returned %s: %s", rel_path, resp.status, body[:200])
    except Exception as e:
        _LOGGER.warning("mkdir /%s failed: %s", rel_path, e)


async def _supervisor_write_file(session, rel_path: str, content: bytes) -> bool:
    """Write content to host path via Supervisor FS API.

    rel_path has no leading slash, must be under an allowed root:
    share/, homeassistant/, ssl/, backup/, media/
    """
    url = f"{_SUPERVISOR_API}/fs/content/{rel_path}"
    headers = {**_supervisor_headers(), "Content-Type": "application/octet-stream"}
    try:
        async with session.put(url, data=content, headers=headers) as resp:
            if resp.status in (200, 201):
                _LOGGER.info("Saved %d bytes → /%s", len(content), rel_path)
                return True
            body = await resp.text()
            _LOGGER.error(
                "Supervisor API returned %s for /%s: %s", resp.status, rel_path, body[:200]
            )
            return False
    except Exception as e:
        _LOGGER.error("Supervisor API error writing /%s: %s", rel_path, e)
        return False


async def async_fetch_updates(hass: HomeAssistant) -> None:
    """Download all JSON files from the update server to the target directory."""
    session = async_get_clientsession(hass)

    _LOGGER.info("Fetching update index from %s", UPDATE_SERVER_URL)
    try:
        async with session.get(UPDATE_SERVER_URL) as resp:
            resp.raise_for_status()
            body = await resp.text()
    except Exception as e:
        _LOGGER.error("Failed to fetch update index: %s", e)
        return

    filenames = re.findall(r'href="([^"]+\.json)"', body)
    if not filenames:
        _LOGGER.warning("No JSON files found at %s", UPDATE_SERVER_URL)
        return

    _LOGGER.info("Found %d update file(s): %s", len(filenames), filenames)

    # UPDATE_TARGET_DIR = /share/matter_motion_lamp/updates
    # The Supervisor FS API only allows access under: share/, homeassistant/, ssl/, backup/, media/
    # /addon_configs/ is NOT accessible via the FS API.
    target_rel = UPDATE_TARGET_DIR.lstrip("/")
    await _supervisor_mkdir(session, target_rel)

    for filename in filenames:
        name = Path(filename).name
        url = UPDATE_SERVER_URL.rstrip("/") + "/" + name
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                content = await resp.read()
        except Exception as e:
            _LOGGER.error("Failed to download %s: %s", url, e)
            continue

        await _supervisor_write_file(session, f"{target_rel}/{name}", content)
