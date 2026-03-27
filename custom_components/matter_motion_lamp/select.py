"""Filtered select entities for Matter Motion Lamp."""

import json
import logging
from pathlib import Path

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import ENTITY_RENAMES_FILE

_LOGGER = logging.getLogger(__name__)

_ENTITY_RENAMES: list[dict] = json.loads(
    (Path(__file__).parent / ENTITY_RENAMES_FILE).read_text(encoding="utf-8")
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up filtered select entities from config entry."""
    entities = [
        FilteredSelectEntity(config)
        for config in _ENTITY_RENAMES
        if "filtered_options" in config
    ]
    async_add_entities(entities)


class FilteredSelectEntity(SelectEntity):
    """A select entity that wraps another select with a filtered option set."""

    def __init__(self, config: dict) -> None:
        self._raw_entity_id: str = config["desired_entity_id"]
        self._attr_options: list[str] = config["filtered_options"]
        self._attr_name: str = config["filtered_name"]
        self._attr_unique_id: str = config["filtered_entity_id"].replace(".", "_")
        self.entity_id: str = config["filtered_entity_id"]

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._raw_entity_id], self._handle_state_change
            )
        )

    @callback
    def _handle_state_change(self, event) -> None:
        self.async_write_ha_state()

    @property
    def current_option(self) -> str | None:
        state = self.hass.states.get(self._raw_entity_id)
        if state and state.state in self._attr_options:
            return state.state
        return None

    async def async_select_option(self, option: str) -> None:
        await self.hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": self._raw_entity_id, "option": option},
            blocking=True,
        )
