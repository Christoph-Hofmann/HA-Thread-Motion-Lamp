"""Sensor platform for Matter Uptime."""

import asyncio
import json
import logging
from datetime import datetime, timedelta

import websockets

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    MATTER_SERVER_URL,
    NODE_ID,
    ENDPOINT_ID,
    CLUSTER_ID,
    ATTRIBUTE_ID,
    SCAN_INTERVAL as _SCAN_INTERVAL_SECONDS,
)

SCAN_INTERVAL = timedelta(seconds=_SCAN_INTERVAL_SECONDS)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Matter Uptime sensor."""
    device_info = None
    for device in dr.async_get(hass).devices.values():
        if device.manufacturer == "Espressif" and device.model == "MotionLamp":
            device_info = DeviceInfo(identifiers=device.identifiers)
            break

    entity = MatterUptimeSensor(entry, device_info)
    async_add_entities([entity], update_before_add=True)

    # Schedule periodic updates
    async def async_update(event_time):
        await entity.async_update()

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            async_update,
            SCAN_INTERVAL,
        )
    )


class MatterUptimeSensor(SensorEntity):
    """Representation of a Matter Uptime sensor."""

    entity_description = SensorEntityDescription(
        key="matter_uptime",
        name="MotionLamp UpTime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
    )

    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo | None) -> None:
        """Initialize the sensor."""
        self._attr_unique_id = f"matter_uptime_{NODE_ID}_{ENDPOINT_ID}_{CLUSTER_ID}_{ATTRIBUTE_ID}"
        self._attr_device_info = device_info
        self._state = None
        self._available = False

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def available(self):
        """Return if sensor is available."""
        return self._available

    async def async_update(self) -> None:
        """Read Uptime attribute from Matter device."""
        try:
            uptime_value = await self._read_matter_attribute()
            if uptime_value is not None:
                self._state = uptime_value
                self._available = True
                _LOGGER.debug(f"Successfully read uptime: {uptime_value} seconds")
            else:
                self._available = False
                _LOGGER.warning("Failed to read uptime attribute - no value returned")
        except Exception as e:
            self._available = False
            _LOGGER.error(f"Error reading Matter uptime attribute: {e}")

    async def _read_matter_attribute(self) -> int | None:
        """Read attribute from Matter Server via WebSocket."""
        attribute_key = f"{ENDPOINT_ID}/{CLUSTER_ID}/{ATTRIBUTE_ID}"
        try:
            async with websockets.connect(MATTER_SERVER_URL) as websocket:
                _LOGGER.debug("Sending start_listening to %s", MATTER_SERVER_URL)
                await websocket.send(json.dumps({"message_id": "1", "command": "start_listening"}))

                response = None
                while True:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    msg = json.loads(raw)
                    _LOGGER.debug("Received message (message_id=%s)", msg.get("message_id"))
                    if msg.get("message_id") == "1":
                        response = msg
                        break

                nodes = response.get("result", [])
                for node in nodes:
                    if node.get("node_id") == NODE_ID:
                        value = node.get("attributes", {}).get(attribute_key)
                        if value is not None:
                            return int(value)
                        _LOGGER.warning("Attribute %s not found for node %s", attribute_key, NODE_ID)
                        return None

                _LOGGER.warning("Node %s not found in start_listening response", NODE_ID)
                return None

        except websockets.exceptions.WebSocketException as e:
            _LOGGER.error("WebSocket connection error: %s", e)
            return None
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout waiting for Matter Server response")
            return None
        except json.JSONDecodeError as e:
            _LOGGER.error("Failed to parse JSON response: %s", e)
            return None