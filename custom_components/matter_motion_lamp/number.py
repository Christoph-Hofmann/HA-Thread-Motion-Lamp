"""LED Count number entity for the WS2812 strip variant."""

import asyncio
import json
import logging
from datetime import timedelta

import aiohttp
import websockets

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    MATTER_SERVER_URL,
    MODEL_NAMES,
    WS2812_MODEL_NAME,
    WS2812_LED_COUNT_MIN,
    WS2812_LED_COUNT_MAX,
    LAMP_ONTIME_ENDPOINT_ID,
    LAMP_ONTIME_CLUSTER_ID,
    LAMP_ONTIME_ATTRIBUTE_ID,
    LAMP_ONTIME_MIN_S,
    LAMP_ONTIME_MAX_S,
    EFFECT_LENGTH_MIN_S,
    EFFECT_LENGTH_MAX_S,
    SCAN_INTERVAL as _SCAN_INTERVAL_SECONDS,
)
from .device_link import child_device_info
from .sensor import _node_id_from_matter_identifier, async_resolve_device_ipv6

SCAN_INTERVAL = timedelta(seconds=_SCAN_INTERVAL_SECONDS)

_LOGGER = logging.getLogger(__name__)

# Dimmable Light device type (0x0101) — identifies the firmware's dedicated
# "LED Count" endpoint. The real lamp endpoint is an Extended Color Light
# (0x010D) instead, so this doesn't collide with it.
_DIMMABLE_LIGHT_DEVICE_TYPE = 0x0101
_DESCRIPTOR_CLUSTER = 29
_DEVICE_TYPE_LIST_ATTR = 0
_LEVEL_CONTROL_CLUSTER = 8
_CURRENT_LEVEL_ATTR = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the LED Count and Lamp On Time number entities."""
    entities: list[NumberEntity] = []

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
        if device.model == WS2812_MODEL_NAME:
            entities.append(LedCountNumberEntity(node_id, device_info))
        entities.append(LampOnTimeNumberEntity(node_id, device_info))
        entities.append(EffectLengthNumberEntity(hass, node_id, device_info))

    async_add_entities(entities, update_before_add=True)

    async def async_update(event_time):
        for entity in entities:
            await entity.async_update()

    entry.async_on_unload(
        async_track_time_interval(hass, async_update, SCAN_INTERVAL)
    )


class LedCountNumberEntity(NumberEntity):
    """How many of the WS2812 strip's physical pixels are actually driven.

    Backed by the firmware's dedicated "LED Count" endpoint — a dummy
    Dimmable Light whose LevelControl CurrentLevel is repurposed as a plain
    1-101 count rather than a percentage (see the led_count endpoint's
    comment in app_main.cpp for why it isn't a ModeSelect: a 101-entry
    SupportedModes list corrupted the TLV stream on a full device
    interview). That endpoint's ID isn't fixed — it depends on which
    optional I2C sensors a given board has — so it's located by device
    type on every read/write rather than a hardcoded endpoint path.
    """

    _attr_native_min_value = WS2812_LED_COUNT_MIN
    _attr_native_max_value = WS2812_LED_COUNT_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:led-strip-variant"

    def __init__(self, node_id: int, device_info: DeviceInfo) -> None:
        self._node_id = node_id
        self._attr_unique_id = f"matter_led_count_{node_id}"
        self._attr_name = "LED Count"
        self._attr_device_info = device_info
        self._attr_native_value = None
        self._available = False
        self._endpoint_id: int | None = None

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def available(self):
        return self._available

    @staticmethod
    def _find_led_count_endpoint(attributes: dict) -> tuple[int | None, int | None]:
        """Return (endpoint_id, current_level) for the Dimmable Light endpoint, if any."""
        for key, value in attributes.items():
            parts = key.split("/")
            if len(parts) != 3 or parts[1] != str(_DESCRIPTOR_CLUSTER) or parts[2] != str(_DEVICE_TYPE_LIST_ATTR):
                continue
            device_types = [dt.get("0") for dt in (value or [])]
            if _DIMMABLE_LIGHT_DEVICE_TYPE in device_types:
                endpoint_id = int(parts[0])
                level_key = f"{endpoint_id}/{_LEVEL_CONTROL_CLUSTER}/{_CURRENT_LEVEL_ATTR}"
                return endpoint_id, attributes.get(level_key)
        return None, None

    async def async_update(self) -> None:
        try:
            async with websockets.connect(MATTER_SERVER_URL) as websocket:
                await websocket.send(json.dumps({"message_id": "1", "command": "start_listening"}))

                while True:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    msg = json.loads(raw)
                    if msg.get("message_id") == "1":
                        break

                for node in msg.get("result", []):
                    if node.get("node_id") != self._node_id:
                        continue
                    endpoint_id, level = self._find_led_count_endpoint(node.get("attributes", {}))
                    if endpoint_id is None or level is None:
                        self._available = False
                        _LOGGER.warning("Node %s: LED Count endpoint not found", self._node_id)
                        return
                    self._endpoint_id = endpoint_id
                    self._attr_native_value = min(max(int(level), WS2812_LED_COUNT_MIN), WS2812_LED_COUNT_MAX)
                    self._available = True
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

    async def async_set_native_value(self, value: float) -> None:
        if self._endpoint_id is None:
            await self.async_update()
        if self._endpoint_id is None:
            _LOGGER.error("Node %s: cannot set LED count, endpoint unknown", self._node_id)
            return

        count = int(value)
        try:
            async with websockets.connect(MATTER_SERVER_URL) as websocket:
                # CurrentLevel is spec-defined as not directly writable —
                # matter-server rejects a raw write_attribute with
                # UNSUPPORTED_WRITE (confirmed via a live test against a
                # real device). Like any Matter dimmable light, it can only
                # be changed via a LevelControl command; the firmware's own
                # real lamp brightness already works this way too (see
                # lamp_set_brightness() reacting to a MoveToLevelWithOnOff
                # command in the serial log, not a raw attribute write).
                command = {
                    "message_id": "1",
                    "command": "device_command",
                    "args": {
                        "node_id": self._node_id,
                        "endpoint_id": self._endpoint_id,
                        "cluster_id": _LEVEL_CONTROL_CLUSTER,
                        "command_name": "MoveToLevelWithOnOff",
                        "payload": {
                            "level": count,
                            "transitionTime": 0,
                            "optionsMask": 0,
                            "optionsOverride": 0,
                        },
                    },
                }
                _LOGGER.debug("Node %s: setting LED count to %d: %s", self._node_id, count, command)
                await websocket.send(json.dumps(command))

                # Wait for the response to *this* request specifically —
                # matter-server sends an unprompted server-info message
                # the instant the connection opens, before any response to
                # our command; a bare single recv() picks that up instead
                # and (worse) closes the connection right after, aborting
                # the write before the device-side round trip completes.
                while True:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    response = json.loads(raw)
                    if response.get("message_id") == "1":
                        break
                _LOGGER.debug("Node %s: set LED count response: %s", self._node_id, response)
        except Exception as e:
            _LOGGER.error("Node %s: error setting LED count: %s", self._node_id, e)
            return

        self._attr_native_value = count
        self.async_write_ha_state()


class LampOnTimeNumberEntity(NumberEntity):
    """How long the lamp stays on before auto-off.

    Backed by the standard OnOff::OnTime attribute (cluster 6, 0x4001) on
    the lamp's own endpoint — always endpoint 1, the first endpoint created
    in app_main(), unlike the LED Count endpoint whose position depends on
    which optional I2C sensors a given board has. OnTime is a genuinely
    directly-writable standard attribute, so this uses write_attribute
    directly rather than a command (contrast LED Count's CurrentLevel,
    which needs MoveToLevelWithOnOff since LevelControl attributes aren't
    directly writable).
    """

    _attr_native_min_value = LAMP_ONTIME_MIN_S
    _attr_native_max_value = LAMP_ONTIME_MAX_S
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, node_id: int, device_info: DeviceInfo) -> None:
        self._node_id = node_id
        self._attr_unique_id = f"matter_lamp_ontime_{node_id}"
        self._attr_name = "Lamp On Time"
        self._attr_device_info = device_info
        self._attr_native_value = None
        self._available = False
        self._attribute_path = f"{LAMP_ONTIME_ENDPOINT_ID}/{LAMP_ONTIME_CLUSTER_ID}/{LAMP_ONTIME_ATTRIBUTE_ID}"

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def available(self):
        return self._available

    async def async_update(self) -> None:
        try:
            async with websockets.connect(MATTER_SERVER_URL) as websocket:
                await websocket.send(json.dumps({"message_id": "1", "command": "start_listening"}))

                while True:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    msg = json.loads(raw)
                    if msg.get("message_id") == "1":
                        break

                for node in msg.get("result", []):
                    if node.get("node_id") != self._node_id:
                        continue
                    value = node.get("attributes", {}).get(self._attribute_path)
                    if value is None:
                        self._available = False
                        _LOGGER.warning("Node %s: OnTime attribute not found", self._node_id)
                        return
                    self._attr_native_value = min(max(int(value), LAMP_ONTIME_MIN_S), LAMP_ONTIME_MAX_S)
                    self._available = True
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

    async def async_set_native_value(self, value: float) -> None:
        seconds = int(value)
        try:
            async with websockets.connect(MATTER_SERVER_URL) as websocket:
                command = {
                    "message_id": "1",
                    "command": "write_attribute",
                    "args": {
                        "node_id": self._node_id,
                        "attribute_path": self._attribute_path,
                        "value": seconds,
                    },
                }
                _LOGGER.debug("Node %s: setting lamp on-time to %ds: %s", self._node_id, seconds, command)
                await websocket.send(json.dumps(command))

                # Wait for the response to *this* request specifically — see
                # LedCountNumberEntity.async_set_native_value() for why a
                # bare single recv() isn't safe here.
                while True:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    response = json.loads(raw)
                    if response.get("message_id") == "1":
                        break
                _LOGGER.debug("Node %s: set lamp on-time response: %s", self._node_id, response)
        except Exception as e:
            _LOGGER.error("Node %s: error setting lamp on-time: %s", self._node_id, e)
            return

        self._attr_native_value = seconds
        self.async_write_ha_state()


class EffectLengthNumberEntity(NumberEntity):
    """How long Blink/Flash/Channel Blink/Channel Flash run before
    auto-stopping (or being cut short via the Effect select's idle option).

    Unlike LED Count/Lamp On Time above, this isn't a Matter attribute at
    all — effect_length_s is plain NVS-backed app state with no cluster of
    its own (see EFFECT_TIMEOUT_NVS_NS in app_driver.cpp), only reachable
    over the firmware's own HTTP REST API. Talks straight to the device's
    IPv6 address (resolved via the same heuristic as IPv6AddressSensor —
    see async_resolve_device_ipv6()), so this entity goes unavailable if
    that address isn't currently reachable, independent of whether the
    device is otherwise online on the Matter fabric.
    """

    _attr_native_min_value = EFFECT_LENGTH_MIN_S
    _attr_native_max_value = EFFECT_LENGTH_MAX_S
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-cog-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, node_id: int, device_info: DeviceInfo) -> None:
        self._hass = hass
        self._node_id = node_id
        self._attr_unique_id = f"matter_effect_length_{node_id}"
        self._attr_name = "Effect Length"
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
            ip, _ = await async_resolve_device_ipv6(self._node_id)
            if ip is None:
                self._available = False
                _LOGGER.warning("Node %s: no IPv6 address to reach HTTP API", self._node_id)
                return

            session = async_get_clientsession(self._hass)
            async with session.get(
                f"http://[{ip}]/sensors", timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json(content_type=None)

            value = data.get("lamp", {}).get("effect_length_s")
            if value is None:
                self._available = False
                _LOGGER.warning("Node %s: effect_length_s missing from /sensors", self._node_id)
                return
            self._attr_native_value = value
            self._available = True
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            self._available = False
            _LOGGER.error("Node %s: error reading effect length over HTTP: %s", self._node_id, e)

    async def async_set_native_value(self, value: float) -> None:
        ip, _ = await async_resolve_device_ipv6(self._node_id)
        if ip is None:
            _LOGGER.error("Node %s: cannot set effect length, no IPv6 address known", self._node_id)
            return

        seconds = int(value)
        try:
            session = async_get_clientsession(self._hass)
            async with session.post(
                f"http://[{ip}]/config/effect_length",
                json={"seconds": seconds},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                # Firmware clamps out-of-range values and echoes back what
                # it actually stored — trust that over the value we sent.
                data = await resp.json(content_type=None)
                _LOGGER.debug("Node %s: set effect length to %ds, response: %s", self._node_id, seconds, data)
                stored = data.get("seconds", seconds)
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            _LOGGER.error("Node %s: error setting effect length: %s", self._node_id, e)
            return

        self._attr_native_value = stored
        self._available = True
        self.async_write_ha_state()
