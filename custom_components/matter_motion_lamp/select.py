"""Action select entities for Matter Motion Lamp."""

import asyncio
import json
import logging
from datetime import timedelta
from pathlib import Path

import websockets

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    ACTIONS_FILE,
    MATTER_SERVER_URL,
    MODEL_NAMES,
    WS2812_MODEL_NAME,
    SCAN_INTERVAL as _SCAN_INTERVAL_SECONDS,
)
from .device_link import child_device_info
from .sensor import _node_id_from_matter_identifier

SCAN_INTERVAL = timedelta(seconds=_SCAN_INTERVAL_SECONDS)

_LOGGER = logging.getLogger(__name__)

_ACTIONS: list[dict] = json.loads(
    (Path(__file__).parent / ACTIONS_FILE).read_text(encoding="utf-8")
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one effect select (and, for the WS2812 variant, one animation select) per MotionLamp device."""
    entities: list[SelectEntity] = []
    animation_entities: list[AnimationSelectEntity] = []

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
        entities.append(EffectSelectEntity(node_id, device_info))

        if device.model == WS2812_MODEL_NAME:
            animation_entity = AnimationSelectEntity(node_id, device_info)
            entities.append(animation_entity)
            animation_entities.append(animation_entity)

    async_add_entities(entities, update_before_add=True)

    async def async_update(event_time):
        for entity in animation_entities:
            await entity.async_update()

    entry.async_on_unload(
        async_track_time_interval(hass, async_update, SCAN_INTERVAL)
    )


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
            # StopEffect (0xFF) — a real spec-defined Identify effect
            # identifier, not a made-up sentinel — tells the firmware to
            # cancel whatever Blink/Flash/Channel Blink/Channel Flash is
            # currently running instead of waiting out its full
            # effect_length_s. Same endpoint/cluster/command shape as the
            # real effects above, just a different payload.
            command = {
                "message_id": "1",
                "command": "device_command",
                "args": {
                    "node_id": self._node_id,
                    "endpoint_id": 1,
                    "cluster_id": 3,
                    "command_name": "TriggerEffect",
                    "payload": {"effectIdentifier": 255, "effectVariant": 0},
                },
            }
            self._current = self._IDLE
            self.async_write_ha_state()
            try:
                async with websockets.connect(MATTER_SERVER_URL) as websocket:
                    _LOGGER.debug("Node %s: sending StopEffect: %s", self._node_id, command)
                    await websocket.send(json.dumps(command))
                    while True:
                        raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                        response = json.loads(raw)
                        if response.get("message_id") == "1":
                            break
                    _LOGGER.debug("Node %s: StopEffect response: %s", self._node_id, response)
            except Exception as e:
                _LOGGER.error("Node %s: error sending StopEffect: %s", self._node_id, e)
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

                # Wait for the response to *this* request specifically —
                # matter-server sends an unprompted server-info message the
                # instant the connection opens, before any response to our
                # command; a bare single recv() picks that up instead and
                # (worse) closes the connection right after, aborting the
                # command before its device-side round trip completes.
                while True:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    response = json.loads(raw)
                    if response.get("message_id") == "1":
                        break
                _LOGGER.debug("Node %s: effect response: %s", self._node_id, response)
        except Exception as e:
            _LOGGER.error("Node %s: error sending effect '%s': %s", self._node_id, option, e)
        finally:
            self._current = self._IDLE
            self.async_write_ha_state()


class AnimationSelectEntity(SelectEntity):
    """Persistent-state select for the WS2812 strip's continuous animations.

    Backed by a standalone Mode Select endpoint (device type 0x0027,
    ModeSelect cluster) — see EffectModesManager's comment in app_main.cpp
    for why these live here instead of on EffectSelectEntity's Identify::
    TriggerEffect mechanism above: the SDK collapses any custom
    effectIdentifier beyond the six spec values to one indistinguishable
    sentinel, so Rainbow/Knight Rider/Color Wave couldn't be told apart
    over TriggerEffect. HA's core Matter integration already creates its
    own select entity for this cluster (on the separate "Matter" device —
    see device_link.py), which is why these options were reachable there
    but not from this integration's own child device; this mirrors them
    here too, using CurrentMode/ChangeToMode directly rather than relying
    on that entity.

    Unlike EffectSelectEntity's momentary triggers, this reflects real
    device state and doesn't self-reset — the strip keeps animating until
    switched back to "Off".
    """

    _MODE_SELECT_DEVICE_TYPE = 0x0027
    _MODE_SELECT_CLUSTER = 80
    _CURRENT_MODE_ATTR = 3
    _DESCRIPTOR_CLUSTER = 29
    _DEVICE_TYPE_LIST_ATTR = 0

    _MODES = {0: "Off", 1: "Rainbow", 2: "Breathe", 3: "Knight Rider", 4: "Color Wave"}
    _MODES_BY_NAME = {name: mode for mode, name in _MODES.items()}

    def __init__(self, node_id: int, device_info: DeviceInfo) -> None:
        self._node_id = node_id
        self._attr_unique_id = f"matter_animation_{node_id}"
        self._attr_name = "Animation"
        self._attr_device_info = device_info
        self._attr_options = list(self._MODES.values())
        self._current: str | None = None
        self._available = False
        self._endpoint_id: int | None = None

    @property
    def current_option(self) -> str | None:
        return self._current

    @property
    def available(self) -> bool:
        return self._available

    def _find_animation_endpoint(self, attributes: dict) -> tuple[int | None, int | None]:
        for key, value in attributes.items():
            parts = key.split("/")
            if len(parts) != 3 or parts[1] != str(self._DESCRIPTOR_CLUSTER) or parts[2] != str(self._DEVICE_TYPE_LIST_ATTR):
                continue
            device_types = [dt.get("0") for dt in (value or [])]
            if self._MODE_SELECT_DEVICE_TYPE in device_types:
                endpoint_id = int(parts[0])
                mode_key = f"{endpoint_id}/{self._MODE_SELECT_CLUSTER}/{self._CURRENT_MODE_ATTR}"
                return endpoint_id, attributes.get(mode_key)
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
                    endpoint_id, mode = self._find_animation_endpoint(node.get("attributes", {}))
                    if endpoint_id is None or mode is None:
                        self._available = False
                        _LOGGER.warning("Node %s: Animation endpoint not found", self._node_id)
                        return
                    self._endpoint_id = endpoint_id
                    self._current = self._MODES.get(int(mode))
                    self._available = self._current is not None
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

    async def async_select_option(self, option: str) -> None:
        mode = self._MODES_BY_NAME.get(option)
        if mode is None:
            return
        if self._endpoint_id is None:
            await self.async_update()
        if self._endpoint_id is None:
            _LOGGER.error("Node %s: cannot set animation, endpoint unknown", self._node_id)
            return

        try:
            async with websockets.connect(MATTER_SERVER_URL) as websocket:
                command = {
                    "message_id": "1",
                    "command": "device_command",
                    "args": {
                        "node_id": self._node_id,
                        "endpoint_id": self._endpoint_id,
                        "cluster_id": self._MODE_SELECT_CLUSTER,
                        "command_name": "ChangeToMode",
                        "payload": {"newMode": mode},
                    },
                }
                _LOGGER.debug("Node %s: setting animation to '%s': %s", self._node_id, option, command)
                await websocket.send(json.dumps(command))

                # Wait for the response to *this* request specifically — see
                # EffectSelectEntity.async_select_option() for why a bare
                # single recv() isn't safe here.
                while True:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    response = json.loads(raw)
                    if response.get("message_id") == "1":
                        break
                _LOGGER.debug("Node %s: set animation response: %s", self._node_id, response)
        except Exception as e:
            _LOGGER.error("Node %s: error setting animation '%s': %s", self._node_id, option, e)
            return

        self._current = option
        self.async_write_ha_state()
