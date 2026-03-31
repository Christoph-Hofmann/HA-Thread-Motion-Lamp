"""Action select entities for Matter Motion Lamp."""

import asyncio
import json
import logging
from pathlib import Path

import websockets

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ACTIONS_FILE, MATTER_SERVER_URL
from .sensor import _node_id_from_matter_identifier

_LOGGER = logging.getLogger(__name__)

_ACTIONS: list[dict] = json.loads(
    (Path(__file__).parent / ACTIONS_FILE).read_text(encoding="utf-8")
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one effect select per MotionLamp device."""
    entities: list[EffectSelectEntity] = []

    for device in dr.async_get(hass).devices.values():
        if device.manufacturer != "Espressif" or device.model != "MotionLamp":
            continue

        node_id = None
        for domain, value in device.identifiers:
            if domain == "matter":
                node_id = _node_id_from_matter_identifier(value)
                break

        if node_id is None:
            _LOGGER.warning("Could not extract node_id for device %s", device.name)
            continue

        entities.append(EffectSelectEntity(node_id, DeviceInfo(identifiers=device.identifiers)))

    async_add_entities(entities)


class EffectSelectEntity(SelectEntity):
    """Select entity that triggers a Matter Identify effect on the device."""

    _IDLE = "—"

    def __init__(self, node_id: int, device_info: DeviceInfo) -> None:
        self._node_id = node_id
        self._attr_unique_id = f"matter_effect_{node_id}"
        self._attr_name = "Effect"
        self._attr_device_info = device_info
        self._attr_options = [self._IDLE] + [a["name"] for a in _ACTIONS]
        self._current = self._IDLE

    @property
    def current_option(self) -> str:
        return self._current

    async def async_select_option(self, option: str) -> None:
        if option == self._IDLE:
            self._current = self._IDLE
            self.async_write_ha_state()
            return

        action = next((a for a in _ACTIONS if a["name"] == option), None)
        if action is None:
            return

        self._current = option
        self.async_write_ha_state()

        try:
            async with websockets.connect(MATTER_SERVER_URL) as websocket:
                command = {
                    "message_id": "1",
                    "command": "device_command",
                    "args": {
                        "node_id": self._node_id,
                        "endpoint_id": action["endpoint_id"],
                        "cluster_id": action["cluster_id"],
                        "command_name": action["command_name"],
                        "payload": action["payload"],
                    },
                }
                _LOGGER.debug("Node %s: sending effect '%s': %s", self._node_id, option, command)
                await websocket.send(json.dumps(command))
                response = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10.0))
                _LOGGER.debug("Node %s: effect response: %s", self._node_id, response)
        except Exception as e:
            _LOGGER.error("Node %s: error sending effect '%s': %s", self._node_id, option, e)
        finally:
            self._current = self._IDLE
            self.async_write_ha_state()
