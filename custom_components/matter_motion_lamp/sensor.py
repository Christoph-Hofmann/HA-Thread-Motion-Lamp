"""Sensor platform for Matter Uptime and the optional LD2410 presence sensor."""

import asyncio
import json
import logging
from datetime import timedelta

import websockets

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

from .const import (
    MATTER_SERVER_URL,
    MODEL_NAMES,
    ENDPOINT_ID,
    CLUSTER_ID,
    ATTRIBUTE_ID,
    SCAN_INTERVAL as _SCAN_INTERVAL_SECONDS,
)
from .device_link import child_device_info

SCAN_INTERVAL = timedelta(seconds=_SCAN_INTERVAL_SECONDS)

_LOGGER = logging.getLogger(__name__)

# HLK-LD2410C mmWave presence sensor — optional, not every MotionLamp has
# one wired up. Its five numeric values live on a vendor-specific cluster
# (moving/still distance+energy, overall detection distance) rather than
# any standard Matter cluster — see LD2410_DATA_CLUSTER_ID in this
# project's firmware (app_priv.h). Its endpoint ID isn't fixed (it's
# appended after whatever optional sensors a given board already has), so
# it's located per-device by checking which endpoint actually has this
# cluster, not by a hardcoded path.
_LD2410_DATA_CLUSTER = 0xFFF1FC10
_LD2410_SENSORS = [
    # (attribute_id, name, unit, icon)
    (0, "Moving Distance", "cm", "mdi:radar"),
    (1, "Moving Energy", "%", "mdi:radar"),
    (2, "Still Distance", "cm", "mdi:radar"),
    (3, "Still Energy", "%", "mdi:radar"),
    (4, "Detection Distance", "cm", "mdi:radar"),
    # Set once per fresh gate-threshold detection, not repeated while the
    # hold timer keeps it occupied — see app_driver.cpp's
    # ld2410_parse_engineering_payload(). Trigger Type: 0 = motion, 1 = still.
    (5, "Trigger Gate", None, "mdi:radar"),
    (6, "Trigger Type", None, "mdi:radar"),
    (7, "Trigger Energy", "%", "mdi:radar"),
    (8, "Trigger Threshold", "%", "mdi:radar"),
]


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


def _format_uptime(seconds: int) -> str:
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    return f"{days}d {hours}h {minutes}m"


async def _discover_ld2410_endpoints(node_ids: list[int]) -> dict[int, int]:
    """One-shot check: which of the given nodes actually have the LD2410
    vendor-specific data cluster, and on which endpoint. Devices without
    the sensor simply won't be in the returned dict.
    """
    result: dict[int, int] = {}
    try:
        async with websockets.connect(MATTER_SERVER_URL) as websocket:
            await websocket.send(json.dumps({"message_id": "1", "command": "start_listening"}))
            while True:
                raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                msg = json.loads(raw)
                if msg.get("message_id") == "1":
                    break
            for node in msg.get("result", []):
                node_id = node.get("node_id")
                if node_id not in node_ids:
                    continue
                for key in node.get("attributes", {}):
                    parts = key.split("/")
                    if len(parts) == 3 and parts[1] == str(_LD2410_DATA_CLUSTER):
                        result[node_id] = int(parts[0])
                        break
    except Exception as e:
        _LOGGER.error("Error discovering LD2410 endpoints: %s", e)
    return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one UpTime sensor plus mirrored Pressure/Humidity sensors per
    MotionLamp device, plus LD2410 sensors for whichever devices actually
    have that sensor wired up."""
    entities: list[SensorEntity] = []
    ld2410_candidates: list[tuple[int, DeviceInfo]] = []

    for device in dr.async_get(hass).devices.values():
        if device.manufacturer != "Espressif" or device.model not in MODEL_NAMES:
            continue

        node_id = None
        for domain, value in device.identifiers:
            if domain == "matter":
                node_id = _node_id_from_matter_identifier(value)
                break

        if node_id is None:
            _LOGGER.warning("Could not extract node_id for device %s", device.name)
            continue

        device_info = child_device_info(device)
        entities.append(MatterUptimeSensor(node_id, device_info))
        entities.append(MirroredSensorEntity(hass, device.id, "pressure", node_id, device_info))
        entities.append(MirroredSensorEntity(hass, device.id, "humidity", node_id, device_info))
        ld2410_candidates.append((node_id, device_info))

    if ld2410_candidates:
        ld2410_endpoints = await _discover_ld2410_endpoints([nid for nid, _ in ld2410_candidates])
        for node_id, device_info in ld2410_candidates:
            endpoint_id = ld2410_endpoints.get(node_id)
            if endpoint_id is None:
                continue
            for attribute_id, name, unit, icon in _LD2410_SENSORS:
                entities.append(
                    LD2410ValueSensor(node_id, endpoint_id, attribute_id, name, unit, icon, device_info)
                )

    async_add_entities(entities, update_before_add=True)

    async def async_update(event_time):
        for entity in entities:
            await entity.async_update()

    entry.async_on_unload(
        async_track_time_interval(hass, async_update, SCAN_INTERVAL)
    )


class MatterUptimeSensor(SensorEntity):
    """Uptime sensor for a Matter device, displayed as Xd Yh Zm."""

    _attr_icon = "mdi:timer-outline"

    def __init__(self, node_id: int, device_info: DeviceInfo) -> None:
        self._node_id = node_id
        self._attr_unique_id = f"matter_uptime_{node_id}"
        self._attr_name = "UpTime"
        self._attr_device_info = device_info
        self._attr_native_value = None
        self._available = False

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def available(self):
        return self._available

    async def async_update(self) -> None:
        try:
            seconds = await self._read_uptime_seconds()
            if seconds is not None:
                self._attr_native_value = _format_uptime(seconds)
                self._available = True
                _LOGGER.debug("Node %s uptime: %s", self._node_id, self._attr_native_value)
            else:
                self._available = False
                _LOGGER.warning("Node %s: uptime not returned", self._node_id)
        except Exception as e:
            self._available = False
            _LOGGER.error("Node %s: error reading uptime: %s", self._node_id, e)

    async def _read_uptime_seconds(self) -> int | None:
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


class LD2410ValueSensor(SensorEntity):
    """One of the HLK-LD2410C's numeric values (distance/energy).

    Backed by a vendor-specific cluster on a dedicated endpoint — see
    _LD2410_DATA_CLUSTER above for why (no standard Matter cluster fits
    these values, and reusing Temperature/Pressure/Humidity would clash
    with real sensors of those types on the same device).
    """

    def __init__(
        self,
        node_id: int,
        endpoint_id: int,
        attribute_id: int,
        name: str,
        unit: str,
        icon: str,
        device_info: DeviceInfo,
    ) -> None:
        self._node_id = node_id
        self._endpoint_id = endpoint_id
        self._attribute_id = attribute_id
        self._attr_unique_id = f"matter_ld2410_{node_id}_{attribute_id}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_device_info = device_info
        self._attr_native_value = None
        self._available = False

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def available(self):
        return self._available

    async def async_update(self) -> None:
        attribute_key = f"{self._endpoint_id}/{_LD2410_DATA_CLUSTER}/{self._attribute_id}"
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
                        if value is not None:
                            self._attr_native_value = value
                            self._available = True
                        else:
                            self._available = False
                            _LOGGER.warning("Node %s: attribute %s not found", self._node_id, attribute_key)
                        return

                self._available = False
                _LOGGER.warning("Node %s not found in start_listening response", self._node_id)

        except websockets.exceptions.WebSocketException as e:
            self._available = False
            _LOGGER.error("Node %s: WebSocket error: %s", self._node_id, e)
        except asyncio.TimeoutError:
            self._available = False
            _LOGGER.error("Node %s: timeout waiting for response", self._node_id)
        except json.JSONDecodeError as e:
            self._available = False
            _LOGGER.error("Node %s: JSON parse error: %s", self._node_id, e)


class MirroredSensorEntity(SensorEntity):
    """Mirrors one HA-core Matter sensor entity onto this integration's child device.

    HA 2026.8 stopped merging entities across integrations' devices (see
    device_link.py), so standard-cluster sensors HA core's Matter
    integration creates (temperature/pressure/humidity/...) only show up
    on the separate "Matter" device unless explicitly mirrored — same
    pattern as MasterLightEntity (light.py) and AnimationSelectEntity
    (select.py), just for a plain read-only value instead of a control.

    Located by device_class on the *Matter* device (not this integration's
    own child device — the source entity lives on the other one), and
    re-resolved on entity-registry changes since HA-core's own sensor
    might not exist yet the moment this integration's platform loads.
    """

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        matter_device_id: str,
        device_class: str,
        node_id: int,
        device_info: DeviceInfo,
    ) -> None:
        self._hass = hass
        self._matter_device_id = matter_device_id
        self._device_class = device_class
        self._attr_unique_id = f"matter_mirror_{device_class}_{node_id}"
        self._attr_name = device_class.replace("_", " ").title()
        self._attr_device_info = device_info
        self._attr_native_value = None
        self._source_entity_id: str | None = None
        self._unsub_state_change = None
        self._available = False

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def available(self):
        return self._available

    def _find_source_entity(self) -> str | None:
        registry = er.async_get(self._hass)
        for entry in registry.entities.values():
            if entry.device_id != self._matter_device_id or entry.domain != "sensor":
                continue
            state = self._hass.states.get(entry.entity_id)
            dc = (state.attributes.get("device_class") if state else None) or entry.original_device_class
            if dc == self._device_class:
                return entry.entity_id
        return None

    def _resubscribe(self) -> None:
        if self._unsub_state_change:
            self._unsub_state_change()
            self._unsub_state_change = None
        self._source_entity_id = self._find_source_entity()
        if self._source_entity_id:
            self._unsub_state_change = async_track_state_change_event(
                self._hass, [self._source_entity_id], self._source_state_changed
            )

    async def async_added_to_hass(self) -> None:
        self._resubscribe()
        self._update_from_source()

        self.async_on_remove(
            self._hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_update
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_state_change:
            self._unsub_state_change()
            self._unsub_state_change = None

    async def _handle_registry_update(self, event) -> None:
        # Only worth re-checking if we don't have a source yet, or the
        # event is about the entity we're already tracking.
        entity_id = event.data.get("entity_id", "")
        if self._source_entity_id and entity_id != self._source_entity_id:
            return
        if not entity_id.startswith("sensor."):
            return

        self._resubscribe()
        self._update_from_source()
        self.async_write_ha_state()

    @callback
    def _source_state_changed(self, event) -> None:
        self._update_from_source()
        self.async_write_ha_state()

    @callback
    def _update_from_source(self) -> None:
        state = self._hass.states.get(self._source_entity_id) if self._source_entity_id else None
        if state is None or state.state in ("unknown", "unavailable"):
            self._available = False
            return

        self._available = True
        self._attr_native_value = state.state
        self._attr_native_unit_of_measurement = state.attributes.get("unit_of_measurement")
        self._attr_device_class = state.attributes.get("device_class")
        self._attr_state_class = state.attributes.get("state_class")
        self._attr_icon = state.attributes.get("icon")
