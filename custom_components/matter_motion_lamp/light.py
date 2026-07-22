"""Master light entity for Matter Motion Lamp — mirrors on/off/brightness to every light on the device."""

import logging

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import LIGHT_COUNT_MODEL_NAMES
from .sensor import _node_id_from_matter_identifier

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one 'All Lights' master entity per dimmable MotionLamp device."""
    entities: list[MasterLightEntity] = []

    for device in dr.async_get(hass).devices.values():
        if device.manufacturer != "Espressif" or device.model not in LIGHT_COUNT_MODEL_NAMES:
            continue

        node_id = None
        for domain, value in device.identifiers:
            if domain == "matter":
                node_id = _node_id_from_matter_identifier(value)
                break

        if node_id is None:
            _LOGGER.warning("Could not extract node_id for device %s", device.name)
            continue

        entities.append(
            MasterLightEntity(hass, device.id, node_id, DeviceInfo(identifiers=device.identifiers))
        )

    async_add_entities(entities)


class MasterLightEntity(LightEntity):
    """Aggregate on/off/brightness control for every light entity on this device.

    Individual light entities (light_1..light_4) are created by HA's core
    matter integration, not by us, and their number changes at runtime via
    the firmware's Light Count control. This entity re-discovers its member
    light entities on every call and whenever the entity registry changes,
    rather than caching a fixed list, so it stays correct as lights are
    added or removed.
    """

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, device_id: str, node_id: int, device_info: DeviceInfo) -> None:
        self._hass = hass
        self._device_id = device_id
        self._attr_unique_id = f"matter_master_light_{node_id}"
        self._attr_name = "All Lights"
        self._attr_device_info = device_info
        self._member_entity_ids: list[str] = []
        self._unsub_state_changes = None

    def _discover_members(self) -> list[str]:
        registry = er.async_get(self._hass)
        return [
            entry.entity_id
            for entry in registry.entities.values()
            if entry.device_id == self._device_id
            and entry.domain == "light"
            and entry.unique_id != self._attr_unique_id
        ]

    def _resubscribe(self) -> None:
        if self._unsub_state_changes:
            self._unsub_state_changes()
            self._unsub_state_changes = None
        self._member_entity_ids = self._discover_members()
        if self._member_entity_ids:
            self._unsub_state_changes = async_track_state_change_event(
                self._hass, self._member_entity_ids, self._member_state_changed
            )

    async def async_added_to_hass(self) -> None:
        self._resubscribe()
        self._update_from_members()

        self.async_on_remove(
            self._hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_update
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_state_changes:
            self._unsub_state_changes()
            self._unsub_state_changes = None

    async def _handle_registry_update(self, event) -> None:
        entity_id = event.data.get("entity_id", "")
        if not entity_id.startswith("light."):
            return

        # Removal: the registry entry is already gone, so we can only tell
        # it was one of ours by checking our own last-known member list.
        if event.data.get("action") == "remove":
            if entity_id not in self._member_entity_ids:
                return
        else:
            entry = er.async_get(self._hass).async_get(entity_id)
            if entry is None or entry.device_id != self._device_id:
                return

        self._resubscribe()
        self._update_from_members()
        self.async_write_ha_state()

    @callback
    def _member_state_changed(self, event) -> None:
        self._update_from_members()
        self.async_write_ha_state()

    @callback
    def _update_from_members(self) -> None:
        states = [self._hass.states.get(eid) for eid in self._member_entity_ids]
        states = [s for s in states if s is not None]
        on_states = [s for s in states if s.state == "on"]

        self._attr_is_on = len(on_states) > 0
        self._attr_available = len(states) > 0

        brightness_values = [
            s.attributes.get(ATTR_BRIGHTNESS)
            for s in on_states
            if s.attributes.get(ATTR_BRIGHTNESS) is not None
        ]
        self._attr_brightness = (
            round(sum(brightness_values) / len(brightness_values)) if brightness_values else None
        )

    async def async_turn_on(self, **kwargs) -> None:
        self._member_entity_ids = self._discover_members()
        if not self._member_entity_ids:
            return
        service_data = {"entity_id": self._member_entity_ids}
        if ATTR_BRIGHTNESS in kwargs:
            service_data[ATTR_BRIGHTNESS] = kwargs[ATTR_BRIGHTNESS]
        await self._hass.services.async_call("light", "turn_on", service_data, blocking=True)

    async def async_turn_off(self, **kwargs) -> None:
        self._member_entity_ids = self._discover_members()
        if not self._member_entity_ids:
            return
        await self._hass.services.async_call(
            "light", "turn_off", {"entity_id": self._member_entity_ids}, blocking=True
        )
