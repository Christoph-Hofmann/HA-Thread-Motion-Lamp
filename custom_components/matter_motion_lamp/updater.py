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


async def _log_supervisor_info(session) -> None:
    """Log Supervisor version for debugging."""
    try:
        async with session.get(
            f"{_SUPERVISOR_API}/supervisor/info", headers=_supervisor_headers()
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                version = data.get("data", {}).get("version", "unknown")
                _LOGGER.debug("Supervisor version: %s", version)
            else:
                _LOGGER.debug("Supervisor info returned %s", resp.status)
    except Exception as e:
        _LOGGER.debug("Could not fetch Supervisor info: %s", e)


async def _supervisor_mkdir(session, rel_path: str) -> None:
    """Ensure directory exists via Supervisor FS API."""
    headers = _supervisor_headers()
    # Try both known endpoint variants
    for url in [
        f"{_SUPERVISOR_API}/fs/mkdir/{rel_path}",
        f"{_SUPERVISOR_API}/files/mkdir/{rel_path}",
    ]:
        try:
            async with session.post(url, headers=headers) as resp:
                if resp.status in (200, 201, 409):  # 409 = already exists
                    _LOGGER.debug("Directory ready via %s (status %s)", url, resp.status)
                    return
        except Exception:
            pass


async def _supervisor_write_file(session, rel_path: str, content: bytes) -> bool:
    """Write content to host path via Supervisor FS API.

    rel_path is the path without a leading slash, e.g.
    'addon_configs/core_matter_server/updates/file.json'
    or 'share/matter_motion_lamp/updates/file.json'
    """
    headers = {**_supervisor_headers(), "Content-Type": "application/octet-stream"}
    for url in [
        f"{_SUPERVISOR_API}/fs/content/{rel_path}",
        f"{_SUPERVISOR_API}/files/content/{rel_path}",
    ]:
        try:
            async with session.put(url, data=content, headers=headers) as resp:
                if resp.status in (200, 201):
                    _LOGGER.info(
                        "Supervisor wrote %d bytes → /%s (via %s)",
                        len(content), rel_path, url,
                    )
                    return True
                body = await resp.text()
                _LOGGER.debug(
                    "Supervisor API %s → %s: %s", url, resp.status, body[:200]
                )
        except Exception as e:
            _LOGGER.debug("Supervisor API error for %s: %s", url, e)

    _LOGGER.error(
        "All Supervisor write endpoints failed for /%s — check Supervisor version "
        "(FS API requires Supervisor >= 2023.11)",
        rel_path,
    )
    return False


async def async_fetch_updates(hass: HomeAssistant) -> None:
    """Download all JSON files from the update server to the target directory."""
    session = async_get_clientsession(hass)

    await _log_supervisor_info(session)

    _LOGGER.info("Fetching update index from %s", UPDATE_SERVER_URL)
    try:
        async with session.get(UPDATE_SERVER_URL) as resp:
            resp.raise_for_status()
            body = await resp.text()
    except Exception as e:
        _LOGGER.error("Failed to fetch update index: %s", e)
        return

    # Find all .json hrefs in the directory listing
    filenames = re.findall(r'href="([^"]+\.json)"', body)
    if not filenames:
        _LOGGER.warning("No JSON files found at %s", UPDATE_SERVER_URL)
        return

    _LOGGER.info("Found %d update file(s): %s", len(filenames), filenames)

    # Derive relative host path (strip leading slash)
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

        rel_path = f"{target_rel}/{name}"
        await _supervisor_write_file(session, rel_path, content)
