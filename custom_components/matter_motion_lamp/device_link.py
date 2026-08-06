"""Shared helper for attaching this integration's entities to a MotionLamp.

HA 2026.8 removed automatic device merging across config entries — reusing
another integration's device identifiers in DeviceInfo used to fold our
entities into the same device HA's core Matter integration created for the
node; now it silently creates a second, disconnected-looking device instead
(see https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/).
via_device_id is the replacement: it links our device as a child of the
Matter device, so at least it shows up nested/associated in the UI, though
it is still a distinct device.

Deliberately does NOT copy the Matter device's manufacturer/model —
__init__.py's _is_motionlamp_device() matches entities to rename/delete by
those exact fields (manufacturer == "Espressif", model in MODEL_NAMES); if
our child device also carried them, that cleanup logic would try to process
it too (and its device-name dedup logic could rename it independently of
the parent, drifting the two names apart).
"""

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


def child_device_info(device) -> DeviceInfo:
    """DeviceInfo for entities we add alongside an existing Matter device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"motion_lamp_{device.id}")},
        via_device_id=device.id,
        name=device.name_by_user or device.name,
        manufacturer="Christoph-Hofmann",
    )
