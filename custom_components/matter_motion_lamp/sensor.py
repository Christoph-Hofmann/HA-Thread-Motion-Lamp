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
    entity = MatterUptimeSensor(entry)
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

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self._attr_unique_id = f"matter_uptime_{NODE_ID}_{ENDPOINT_ID}_{CLUSTER_ID}_{ATTRIBUTE_ID}"
        self._attr_device_info = None
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
        try:
            # Connect to Matter Server
            async with websockets.connect(MATTER_SERVER_URL) as websocket:
                # First, start listening to get node information
                start_listening = {
                    "message_id": "1",
                    "command": "start_listening"
                }
                await websocket.send(json.dumps(start_listening))

                # Wait for the start_listening response before proceeding
                await asyncio.wait_for(websocket.recv(), timeout=10.0)

                # Read the specific attribute
                read_command = {
                    "message_id": "2",
                    "command": "read_attribute",
                    "args": {
                        "node_id": NODE_ID,
                        "endpoint_id": ENDPOINT_ID,
                        "cluster_id": CLUSTER_ID,
                        "attribute_id": ATTRIBUTE_ID
                    }
                }
                
                _LOGGER.debug(f"Sending command: {read_command}")
                await websocket.send(json.dumps(read_command))
                
                # Receive response
                response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                response_data = json.loads(response)
                _LOGGER.debug(f"Received response: {response_data}")
                
                # Parse the response to extract the attribute value
                if "result" in response_data:
                    result = response_data["result"]
                    # The attribute value might be nested in different ways
                    if isinstance(result, dict):
                        if "value" in result:
                            return result["value"]
                        elif "attribute_value" in result:
                            return result["attribute_value"]
                        elif "UpTime" in result:
                            return result["UpTime"]
                    elif isinstance(result, (int, float)):
                        return int(result)
                
                # Alternative: check for attribute update events
                if "event" in response_data and response_data["event"] == "attribute_updated":
                    if "value" in response_data:
                        return response_data["value"]
                        
                return None
                
        except websockets.exceptions.WebSocketException as e:
            _LOGGER.error(f"WebSocket connection error: {e}")
            return None
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout waiting for Matter Server response")
            return None
        except json.JSONDecodeError as e:
            _LOGGER.error(f"Failed to parse JSON response: {e}")
            return None