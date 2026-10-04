"""Config flow: region plus the appKey/appSecret of an EZVIZ Open Platform app."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import EzvizCloudApi, EzvizCloudAuthError, EzvizCloudError
from .const import CONF_APP_KEY, CONF_APP_SECRET, CONF_REGION, DOMAIN, REGIONS

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REGION, default="eu"): SelectSelector(
            SelectSelectorConfig(
                options=list(REGIONS),
                mode=SelectSelectorMode.DROPDOWN,
                translation_key=CONF_REGION,
            )
        ),
        vol.Required(CONF_APP_KEY): TextSelector(),
        vol.Required(CONF_APP_SECRET): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class EzvizCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the Open Platform credentials and check them against the platform."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the only step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            app_key = user_input[CONF_APP_KEY].strip()
            await self.async_set_unique_id(app_key)
            self._abort_if_unique_id_configured()
            api = EzvizCloudApi(
                async_get_clientsession(self.hass),
                REGIONS[user_input[CONF_REGION]],
                app_key,
                user_input[CONF_APP_SECRET].strip(),
            )
            try:
                await api.async_get_token()
            except EzvizCloudAuthError:
                errors["base"] = "invalid_auth"
            except EzvizCloudError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"EZVIZ Cloud ({user_input[CONF_REGION].upper()})",
                    data={
                        CONF_REGION: user_input[CONF_REGION],
                        CONF_APP_KEY: app_key,
                        CONF_APP_SECRET: user_input[CONF_APP_SECRET].strip(),
                    },
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(DATA_SCHEMA, user_input),
            errors=errors,
        )
