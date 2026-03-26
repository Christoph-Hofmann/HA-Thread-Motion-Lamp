"""Config flow for Matter Motion Lamp."""

from homeassistant import config_entries
from .const import DOMAIN


class MatterMotionLampConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Matter Motion Lamp."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step — no user input needed, all values are constants."""
        return self.async_create_entry(
            title="Matter Motion Lamp",
            data={},
        )
