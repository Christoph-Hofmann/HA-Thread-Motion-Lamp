"""Fetch JSON update files from the update server."""

import logging
import re
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import UPDATE_SERVER_URL, UPDATE_TARGET_DIR

_LOGGER = logging.getLogger(__name__)


async def async_fetch_updates(hass: HomeAssistant) -> None:
    """Download all JSON files from the update server to the target directory."""
    session = async_get_clientsession(hass)
    target = Path(UPDATE_TARGET_DIR)
    target.mkdir(parents=True, exist_ok=True)

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

    for filename in filenames:
        url = UPDATE_SERVER_URL.rstrip("/") + "/" + Path(filename).name
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                content = await resp.read()
            dest = target / Path(filename).name
            dest.write_bytes(content)
            if dest.exists():
                _LOGGER.info("Saved update file: %s (%d bytes)", dest, dest.stat().st_size)
            else:
                _LOGGER.error("Write reported success but file not found: %s", dest)
        except Exception as e:
            _LOGGER.error("Failed to download %s: %s", url, e)
