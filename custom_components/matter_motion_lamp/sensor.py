"""Sensor platform for Matter Uptime."""

import asyncio
import json
import logging
from datetime import timedelta

import websockets

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.core import HomeAssistant

from .const import (
    MATTER_SERVER_URL,
    ENDPOINT_ID,
    CLUSTER_ID,
    ATTRIBUTE_ID,
    SCAN_INTERVAL as _SCAN_INTERVAL_SECONDS,
)

SCAN_INTERVAL = timedelta(seconds=_SCAN_INTERVAL_SECONDS)

_LOGGER = logging.getLogger(__name__)


def _node_id_from_matter_identifier(value: str) -> int | None:
    """Extract numeric node ID from a Matter device identifier string.

    Format: deviceid_{fabric_id}-{node_id_hex}-MatterNodeDevice
    """
    parts = value.split("-")
    if len(parts) >= 2:
        try:
            return int(parts[-2], 16)
        except ValueError:
            pass
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one UpTime sensor per MotionLamp device."""
    entities: list[MatterUptimeSensor] = []

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

        device_info = DeviceInfo(identifiers=device.identifiers)
        entities.append(MatterUptimeSensor(node_id, device_info))

    async_add_entities(entities, update_before_add=True)

    async def async_update(event_time):
        for entity in entities:
            await entity.async_update()

    entry.async_on_unload(
        async_track_time_interval(hass, async_update, SCAN_INTERVAL)
    )


class MatterUptimeSensor(SensorEntity):
    """Representation of a Matter Uptime sensor."""

    def __init__(self, node_id: int, device_info: DeviceInfo) -> None:
        self._node_id = node_id
        self._attr_unique_id = f"matter_uptime_{node_id}_{ENDPOINT_ID}_{CLUSTER_ID}_{ATTRIBUTE_ID}"
        self._attr_name = "UpTime"
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_info = device_info
        self._state = None
        self._available = False

    @property
    def native_value(self):
        return self._state

    @property
    def available(self):
        return self._available

    async def async_update(self) -> None:
        try:
            value = await self._read_uptime()
            if value is not None:
                self._state = value
                self._available = True
                _LOGGER.debug("Node %s uptime: %s seconds", self._node_id, value)
            else:
                self._available = False
                _LOGGER.warning("Node %s: uptime not returned", self._node_id)
        except Exception as e:
            self._available = False
            _LOGGER.error("Node %s: error reading uptime: %s", self._node_id, e)

    async def _read_uptime(self) -> int | None:
        attribute_key = f"{ENDPOINT_ID}/{CLUSTER_ID}/{ATTRIBUTE_ID}"
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
