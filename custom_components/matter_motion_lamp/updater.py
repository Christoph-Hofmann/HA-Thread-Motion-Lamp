"""Fetch OTA firmware files from the update server for Matter Server to import."""

import functools
import logging
import re
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import UPDATE_SERVER_URL, UPDATE_TARGET_DIR

_LOGGER = logging.getLogger(__name__)


async def async_fetch_updates(hass: HomeAssistant) -> None:
    """Download OTA files from the update server to Matter Server's provider directory.

    UPDATE_TARGET_DIR must match the Matter Server add-on's --ota-provider-dir
    exactly, or it silently never picks up anything — that add-on only scans
    the one directory it was launched with (confirmed via its startup command
    line in the add-on log), it doesn't watch anywhere else.

    Matter Server (the JS/matter.js-based add-on) only scans that directory
    for .ota binary files — it reads vid/pid/software version directly from
    each file's own embedded header and *ignores .json files entirely*, so a
    JSON manifest alone (what this used to fetch) is never enough on its own.
    We still fetch the .json files too since they're harmless and useful as
    human-readable notes, but the .ota files are what actually matters.
    Matter Server deletes each .ota file from this directory once it's
    successfully imported, so re-fetching everything on every call is
    intentional, not wasteful — anything already known to Matter Server just
    won't be sitting here anymore.
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

    filenames = re.findall(r'href="([^"]+\.(?:json|ota))"', body)
    if not filenames:
        _LOGGER.warning("No update files found at %s", UPDATE_SERVER_URL)
        return

    _LOGGER.info("Found %d update file(s): %s", len(filenames), filenames)

    target = Path(UPDATE_TARGET_DIR)
    try:
        await hass.async_add_executor_job(functools.partial(target.mkdir, parents=True, exist_ok=True))
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
            await hass.async_add_executor_job(dest.write_bytes, content)
            _LOGGER.info("Saved %s (%d bytes) → %s", name, len(content), dest)
        except OSError as e:
            _LOGGER.error("Failed to write %s: %s", dest, e)
