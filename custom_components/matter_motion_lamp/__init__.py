"""Matter Motion Lamp Component."""

import asyncio
import json
import logging
from pathlib import Path
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.config_entries import ConfigEntry
from .const import (
    DOMAIN,
    MANUFACTURER_ID,
    MODEL_NAME,
    MODEL_ID_MIN,
    MODEL_ID_MAX,
    ENTITY_RENAMES_FILE,
)

_LOGGER = logging.getLogger(__name__)

_ENTITY_RENAMES: list[dict] = json.loads(
    (Path(__file__).parent / ENTITY_RENAMES_FILE).read_text(encoding="utf-8")
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Matter Motion Lamp from a config entry."""

    async def check_and_rename_device(device, entity_registry) -> None:
        """Check if device matches Matter IDs and rename if needed."""
        _LOGGER.debug("Checking device#1: %s (manufacturer: %s, model: %s, identifiers: %s)",
                      device.name, device.manufacturer, device.model, device.identifiers)
        manufacturer_matches = False
        model_matches = False

        # Check the manufacturer field
        if device.manufacturer and str(device.manufacturer) == "Espressif":
            manufacturer_matches = True
            _LOGGER.debug("Manufacturer matched by name: %s (expected manufacturer_id: %s)", device.manufacturer, MANUFACTURER_ID)

        # Check the model field (numeric range or known model name)
        if device.model:
            if device.model == MODEL_NAME:
                model_matches = True
                _LOGGER.debug("Model matched by name: %s (model_id range: %s-%s)", device.model, MODEL_ID_MIN, MODEL_ID_MAX)
            else:
                try:
                    model_id = int(device.model)
                    if MODEL_ID_MIN <= model_id <= MODEL_ID_MAX:
                        model_matches = True
                        _LOGGER.debug("Model matched by id: %s", model_id)
                except (ValueError, TypeError):
                    pass

        # Check Matter device identifiers (may encode both manufacturer and model)
        for identifier in device.identifiers:
            if len(identifier) >= 2:
                domain, value = identifier
                if domain == "matter" or "matter" in str(domain).lower():
                    _LOGGER.debug("Matter identifier for %s: domain=%s, value=%s", device.name, domain, value)
                    if str(MANUFACTURER_ID) in str(value):
                        manufacturer_matches = True
                        try:
                            model_id = int(str(value).split("_")[-1])
                            _LOGGER.debug("Parsed manufacturer_id=%s, model_id=%s", MANUFACTURER_ID, model_id)
                            if MODEL_ID_MIN <= model_id <= MODEL_ID_MAX:
                                model_matches = True
                        except (ValueError, IndexError):
                            pass

        # Both manufacturer AND model must match
        if not (manufacturer_matches and model_matches):
            return

        _LOGGER.info("Processing target device: %s (ID: %s)", device.name, device.id)

        # Iterate over all configured entity actions
        for entry in _ENTITY_RENAMES:
            source_entity_id = entry["source_entity_id"]
            action = entry.get("action", "rename")

            entity_entry = entity_registry.async_get(source_entity_id)
            if entity_entry is None or entity_entry.device_id != device.id:
                _LOGGER.debug(
                    "Source entity %s not found on device %s", source_entity_id, device.id
                )
                continue

            if action == "delete":
                _LOGGER.info("Deleting entity %s", source_entity_id)
                entity_registry.async_remove(source_entity_id)
                _LOGGER.info("Successfully deleted %s", source_entity_id)
            else:
                desired_entity_id = entry["desired_entity_id"]
                desired_name = entry["desired_name"]

                unit = entry.get("unit")
                precision = entry.get("precision")

                already_renamed = entity_entry.entity_id == desired_entity_id
                already_unit = entity_entry.unit_of_measurement == unit if unit else True
                already_precision = entity_entry.options.get("sensor", {}).get("display_precision") == precision if precision is not None else True

                if already_renamed and already_unit and already_precision:
                    _LOGGER.debug("Entity %s already up to date, skipping", desired_entity_id)
                    continue

                _LOGGER.info("Updating entity %s → %s", source_entity_id, desired_entity_id)
                try:
                    kwargs = {"name": desired_name}
                    if not already_renamed:
                        kwargs["new_entity_id"] = desired_entity_id
                    if unit:
                        kwargs["unit_of_measurement"] = unit
                    entity_registry.async_update_entity(entity_entry.entity_id, **kwargs)
                    if precision is not None:
                        entity_registry.async_update_entity_options(
                            desired_entity_id,
                            "sensor",
                            {"display_precision": precision},
                        )
                    _LOGGER.info("Successfully updated %s", desired_entity_id)
                except ValueError as err:
                    _LOGGER.error("Failed to update entity %s: %s", source_entity_id, err)

    _source_entity_ids = {r["source_entity_id"] for r in _ENTITY_RENAMES}

    async def async_entity_registry_updated(event) -> None:
        """Handle entity registry updated events — catches new entities as they are created."""
        if event.data.get("action") != "create":
            return
        entity_id = event.data.get("entity_id")
        if entity_id not in _source_entity_ids:
            return
        _LOGGER.debug("Source entity created: %s — scheduling rename", entity_id)

        async def _delayed_rename() -> None:
            await asyncio.sleep(5)
            _LOGGER.debug("Delayed rename triggered for %s", entity_id)
            device_registry = dr.async_get(hass)
            entity_registry = er.async_get(hass)
            entity_entry = entity_registry.async_get(entity_id)
            if entity_entry is None:
                return
            device = device_registry.async_get(entity_entry.device_id)
            if device:
                await check_and_rename_device(device, entity_registry)

        hass.async_create_task(_delayed_rename())

    async def async_startup(_event=None) -> None:
        """Scan all existing devices on startup."""
        _LOGGER.info("Matter Motion Lamp scanning existing devices...")
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        for device in device_registry.devices.values():
            await check_and_rename_device(device, entity_registry)

    # Listen for new entities being registered (handles newly added devices)
    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, async_entity_registry_updated)
    )

    # Run immediately if HA is already running, otherwise wait for startup
    if hass.is_running:
        await async_startup()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, async_startup)

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "select"])

    _LOGGER.info("Matter Motion Lamp component loaded")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, ["sensor", "select"])
