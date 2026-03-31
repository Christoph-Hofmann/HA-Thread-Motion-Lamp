"""Fetch JSON update files from the update server."""

import logging
import re
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import UPDATE_SERVER_URL, UPDATE_TARGET_DIR

_LOGGER = logging.getLogger(__name__)


async def async_fetch_updates(hass: HomeAssistant) -> None:
    """Download all JSON files from the update server to the target directory.

    Writes to UPDATE_TARGET_DIR using direct file I/O.  /share/ is a proper
    bind-mount in the HA core container so files written there are visible on
    the host — unlike /addon_configs/ which only hits the container overlay.
    """
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

    target = Path(UPDATE_TARGET_DIR)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _LOGGER.error("Cannot create target directory %s: %s", target, e)
        return

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

        dest = target / name
        try:
            dest.write_bytes(content)
            _LOGGER.info("Saved %s (%d bytes) → %s", name, len(content), dest)
        except OSError as e:
            _LOGGER.error("Failed to write %s: %s", dest, e)
