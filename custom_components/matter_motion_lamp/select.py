"""Filtered and action select entities for Matter Motion Lamp."""

import asyncio
import json
import logging
import os
from pathlib import Path

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import ACTIONS_FILE, ENTITY_RENAMES_FILE

_LOGGER = logging.getLogger(__name__)

_ENTITY_RENAMES: list[dict] = json.loads(
    (Path(__file__).parent / ENTITY_RENAMES_FILE).read_text(encoding="utf-8")
)

_ACTIONS: list[dict] = json.loads(
    (Path(__file__).parent / ACTIONS_FILE).read_text(encoding="utf-8")
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up filtered and action select entities from config entry."""
    entities: list[SelectEntity] = [
        FilteredSelectEntity(config)
        for config in _ENTITY_RENAMES
        if "filtered_options" in config
    ]
    entities += [ActionSelectEntity(config) for config in _ACTIONS]
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


class ActionSelectEntity(SelectEntity):
    """A select entity whose options each trigger a shell command."""

    _IDLE = "—"

    def __init__(self, config: dict) -> None:
        self.entity_id: str = config["entity_id"]
        self._attr_name: str = config["name"]
        self._attr_unique_id: str = config["entity_id"].replace(".", "_")
        self._commands: dict[str, list[str]] = {
            opt["name"]: opt["command"] for opt in config["options"]
        }
        self._attr_options: list[str] = [self._IDLE] + list(self._commands.keys())
        self._current: str = self._IDLE

    @property
    def current_option(self) -> str:
        return self._current

    async def async_select_option(self, option: str) -> None:
        if option == self._IDLE:
            self._current = self._IDLE
            self.async_write_ha_state()
            return

        self._current = option
        self.async_write_ha_state()

        command = [os.path.expanduser(arg) for arg in self._commands[option]]
        _LOGGER.info("Running action '%s': %s", option, command)
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                _LOGGER.info("Action '%s' completed successfully", option)
            else:
                _LOGGER.error("Action '%s' failed (rc=%s): %s", option, proc.returncode, stderr.decode())
        except Exception as err:
            _LOGGER.error("Action '%s' error: %s", option, err)
        finally:
            self._current = self._IDLE
            self.async_write_ha_state()
