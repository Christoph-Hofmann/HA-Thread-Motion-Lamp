"""Light Count control for Matter Motion Lamp (dimmable variant)."""

import asyncio
import json
import logging
from datetime import timedelta

import websockets

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    LAMP_ENDPOINT_ID,
    LIGHT_COUNT_MODEL_NAME,
    MATTER_SERVER_URL,
    MODE_SELECT_CLUSTER_ID,
    MODE_SELECT_CURRENT_MODE_ATTRIBUTE_ID,
    SCAN_INTERVAL as _SCAN_INTERVAL_SECONDS,
)
from .sensor import _node_id_from_matter_identifier

SCAN_INTERVAL = timedelta(seconds=_SCAN_INTERVAL_SECONDS)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one Light Count number per dimmable MotionLamp device."""
    entities: list[LightCountNumber] = []

    for device in dr.async_get(hass).devices.values():
        if device.manufacturer != "Espressif" or device.model != LIGHT_COUNT_MODEL_NAME:
            continue

        node_id = None
        for domain, value in device.identifiers:
            if domain == "matter":
                node_id = _node_id_from_matter_identifier(value)
                break

        if node_id is None:
            _LOGGER.warning("Could not extract node_id for device %s", device.name)
            continue

        entities.append(LightCountNumber(node_id, DeviceInfo(identifiers=device.identifiers)))

    async_add_entities(entities, update_before_add=True)

    async def async_update(event_time):
        for entity in entities:
            await entity.async_update()

    entry.async_on_unload(
        async_track_time_interval(hass, async_update, SCAN_INTERVAL)
    )


class LightCountNumber(NumberEntity):
    """Number entity controlling how many PWM lights (1-4) a MotionLamp drives."""

    _attr_icon = "mdi:lightbulb-multiple"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 4
    _attr_native_step = 1

    def __init__(self, node_id: int, device_info: DeviceInfo) -> None:
        self._node_id = node_id
        self._attr_unique_id = f"matter_light_count_{node_id}"
        self._attr_name = "Light Count"
        self._attr_device_info = device_info
        self._attr_native_value = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def async_update(self) -> None:
        try:
            count = await self._read_light_count()
            if count is not None:
                self._attr_native_value = count
                self._available = True
                _LOGGER.debug("Node %s light count: %s", self._node_id, count)
            else:
                self._available = False
                _LOGGER.warning("Node %s: light count not returned", self._node_id)
        except Exception as e:
            self._available = False
            _LOGGER.error("Node %s: error reading light count: %s", self._node_id, e)

    async def async_set_native_value(self, value: float) -> None:
        new_mode = int(value)
        try:
            async with websockets.connect(MATTER_SERVER_URL) as websocket:
                command = {
                    "message_id": "1",
                    "command": "device_command",
                    "args": {
                        "node_id": self._node_id,
                        "endpoint_id": LAMP_ENDPOINT_ID,
                        "cluster_id": MODE_SELECT_CLUSTER_ID,
                        "command_name": "ChangeToMode",
                        "payload": {"newMode": new_mode},
                    },
                }
                _LOGGER.debug("Node %s: setting light count to %s: %s", self._node_id, new_mode, command)
                await websocket.send(json.dumps(command))
                response = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10.0))
                _LOGGER.debug("Node %s: light count response: %s", self._node_id, response)
            self._attr_native_value = new_mode
            self._available = True
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error("Node %s: error setting light count to %s: %s", self._node_id, new_mode, e)

    async def _read_light_count(self) -> int | None:
        attribute_key = f"{LAMP_ENDPOINT_ID}/{MODE_SELECT_CLUSTER_ID}/{MODE_SELECT_CURRENT_MODE_ATTRIBUTE_ID}"
        try:
            async with websockets.connect(MATTER_SERVER_URL) as websocket:
                _LOGGER.debug("Node %s: sending start_listening", self._node_id)
                await websocket.send(json.dumps({"message_id": "1", "command": "start_listening"}))

                while True:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    msg = json.loads(raw)
                    if msg.get("message_id") == "1":
                        break

                for node in msg.get("result", []):
                    if node.get("node_id") == self._node_id:
                        value = node.get("attributes", {}).get(attribute_key)
                        if value is not None:
                            return int(value)
                        _LOGGER.warning("Node %s: attribute %s not found", self._node_id, attribute_key)
                        return None

                _LOGGER.warning("Node %s not found in start_listening response", self._node_id)
                return None

        except websockets.exceptions.WebSocketException as e:
            _LOGGER.error("Node %s: WebSocket error: %s", self._node_id, e)
            return None
        except asyncio.TimeoutError:
            _LOGGER.error("Node %s: timeout waiting for response", self._node_id)
            return None
        except json.JSONDecodeError as e:
            _LOGGER.error("Node %s: JSON parse error: %s", self._node_id, e)
            return None
