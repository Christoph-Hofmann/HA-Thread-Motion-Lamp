"""Fetch JSON update files from the update server and write via Supervisor API."""

import base64
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


async def _supervisor_mkdir(session, path: str) -> None:
    """Create directory on host via Supervisor FS API."""
    url = f"{_SUPERVISOR_API}/fs/mkdir"
    try:
        async with session.post(url, headers=_supervisor_headers(), json={"path": path}) as resp:
            if resp.status in (200, 201):
                _LOGGER.debug("Directory ready: %s", path)
            else:
                body = await resp.text()
                _LOGGER.warning("mkdir %s returned %s: %s", path, resp.status, body[:200])
    except Exception as e:
        _LOGGER.warning("mkdir %s failed: %s", path, e)


async def _supervisor_write_file(session, path: str, content: bytes) -> bool:
    """Write file on host via Supervisor FS API (POST /fs/file, base64 content)."""
    url = f"{_SUPERVISOR_API}/fs/file"
    body = {
        "path": path,
        "content": base64.b64encode(content).decode(),
    }
    try:
        async with session.post(url, headers=_supervisor_headers(), json=body) as resp:
            if resp.status in (200, 201):
                _LOGGER.info("Saved %d bytes → %s", len(content), path)
                return True
            text = await resp.text()
            _LOGGER.error("Supervisor /fs/file returned %s for %s: %s", resp.status, path, text[:200])
            return False
    except Exception as e:
        _LOGGER.error("Supervisor /fs/file error for %s: %s", path, e)
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

    await _supervisor_mkdir(session, UPDATE_TARGET_DIR)

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

        await _supervisor_write_file(session, f"{UPDATE_TARGET_DIR}/{name}", content)
