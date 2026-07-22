"""LED Count number entity for the WS2812 RGB strip MotionLamp variant."""

import asyncio
import json
import logging

import websockets

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    LAMP_ENDPOINT_ID,
    LED_COUNT_ATTRIBUTE_ID,
    LED_COUNT_CLUSTER_ID,
    LED_COUNT_MAX,
    LED_COUNT_MIN,
    MATTER_SERVER_URL,
    WS2812_MODEL_NAME,
)
from .sensor import _node_id_from_matter_identifier

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one LED Count entity per WS2812 RGB strip MotionLamp device."""
    entities: list[LedCountNumber] = []

    for device in dr.async_get(hass).devices.values():
        if device.manufacturer != "Espressif" or device.model != WS2812_MODEL_NAME:
            continue

        node_id = None
        for domain, value in device.identifiers:
            if domain == "matter":
                node_id = _node_id_from_matter_identifier(value)
                break

        if node_id is None:
            _LOGGER.warning("Could not extract node_id for device %s", device.name)
            continue

        entities.append(LedCountNumber(node_id, DeviceInfo(identifiers=device.identifiers)))

    async_add_entities(entities)


class LedCountNumber(NumberEntity):
    """Number of the strip's physical LEDs actually driven with color.

    Reads/writes a custom vendor-specific Matter attribute directly over the
    Matter Server websocket — same approach EffectSelectEntity (select.py)
    uses for identify effects, since this isn't a standard cluster HA's core
    Matter integration would surface an entity for on its own.
    """

    _attr_native_min_value = LED_COUNT_MIN
    _attr_native_max_value = LED_COUNT_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:led-strip-variant"
    _attr_should_poll = True

    def __init__(self, node_id: int, device_info: DeviceInfo) -> None:
        self._node_id = node_id
        self._attr_unique_id = f"matter_led_count_{node_id}"
        self._attr_name = "LED Count"
        self._attr_device_info = device_info
        self._attr_native_value = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def async_update(self) -> None:
        try:
            value = await self._read_led_count()
            if value is not None:
                self._attr_native_value = value
                self._available = True
            else:
                self._available = False
                _LOGGER.warning("Node %s: LED count not returned", self._node_id)
        except Exception as e:
            self._available = False
            _LOGGER.error("Node %s: error reading LED count: %s", self._node_id, e)

    async def _read_led_count(self) -> int | None:
        attribute_key = f"{LAMP_ENDPOINT_ID}/{LED_COUNT_CLUSTER_ID}/{LED_COUNT_ATTRIBUTE_ID}"
        try:
            async with websockets.connect(MATTER_SERVER_URL) as websocket:
                await websocket.send(json.dumps({"message_id": "1", "command": "start_listening"}))

                while True:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    msg = json.loads(raw)
                    if msg.get("message_id") == "1":
                        break

                for node in msg.get("result", []):
                    if node.get("node_id") == self._node_id:
                        value = node.get("attributes", {}).get(attribute_key)
                        return int(value) if value is not None else None

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

    async def async_set_native_value(self, value: float) -> None:
        led_count = int(value)
        attribute_path = f"{LAMP_ENDPOINT_ID}/{LED_COUNT_CLUSTER_ID}/{LED_COUNT_ATTRIBUTE_ID}"
        try:
            async with websockets.connect(MATTER_SERVER_URL) as websocket:
                command = {
                    "message_id": "1",
                    "command": "write_attribute",
                    "args": {
                        "node_id": self._node_id,
                        "attribute_path": attribute_path,
                        "value": led_count,
                    },
                }
                _LOGGER.debug("Node %s: writing LED count: %s", self._node_id, command)
                await websocket.send(json.dumps(command))
                response = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10.0))
                _LOGGER.debug("Node %s: write_attribute response: %s", self._node_id, response)
        except Exception as e:
            _LOGGER.error("Node %s: error writing LED count: %s", self._node_id, e)
            return

        self._attr_native_value = led_count
        self._available = True
        self.async_write_ha_state()
