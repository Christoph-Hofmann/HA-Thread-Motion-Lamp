"""Button platform for Matter Motion Lamp."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MATTER_SERVER_ADDON_SLUG
from .updater import async_fetch_updates

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([
        FetchUpdatesButton(hass, entry),
        RestartMatterServerButton(hass, entry),
    ])


class FetchUpdatesButton(ButtonEntity):
    """Button that manually triggers the update file fetch."""

    _attr_unique_id = "matter_motion_lamp_fetch_updates"
    _attr_name = "Fetch Updates"
    _attr_icon = "mdi:cloud-download"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Matter Motion Lamp",
            manufacturer="Christoph-Hofmann",
        )

    async def async_press(self) -> None:
        _LOGGER.info("Fetch Updates button pressed")
        await async_fetch_updates(self._hass)


class RestartMatterServerButton(ButtonEntity):
    """Button that restarts the Matter Server add-on.

    Useful after a node's dynamic endpoints change (e.g. this integration's
    light-count feature) — python-matter-server can end up with a stale
    cached node/entity mapping that survives a device re-interview and even
    a device power-cycle; restarting the add-on forces it to rebuild that
    cache from scratch. Only works on Supervised/HAOS installs where the
    add-on is installed under MATTER_SERVER_ADDON_SLUG.
    """

    _attr_unique_id = "matter_motion_lamp_restart_matter_server"
    _attr_name = "Restart Matter Server"
    _attr_icon = "mdi:restart"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Matter Motion Lamp",
            manufacturer="Christoph-Hofmann",
        )

    async def async_press(self) -> None:
        _LOGGER.info("Restart Matter Server button pressed")
        try:
            await self._hass.services.async_call(
                "hassio", "addon_restart", {"addon": MATTER_SERVER_ADDON_SLUG}, blocking=True
            )
            _LOGGER.info("Matter Server add-on restart requested")
        except Exception as e:
            _LOGGER.error("Failed to restart Matter Server add-on: %s", e)
