"""Button platform for Matter Motion Lamp."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .updater import async_fetch_updates

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([FetchUpdatesButton(hass, entry)])


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
