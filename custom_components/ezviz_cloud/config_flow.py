"""Config flow: region plus the appKey/appSecret of an EZVIZ Open Platform app."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import Camera, EzvizCloudApi, EzvizCloudAuthError, EzvizCloudError
from .const import (
    CONF_APP_KEY,
    CONF_APP_SECRET,
    CONF_CODE,
    CONF_CODES,
    CONF_REGION,
    CONF_SERIAL,
    DOMAIN,
    REGIONS,
)

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

    @staticmethod
    @callback
    def async_get_options_flow(_entry: ConfigEntry) -> EzvizCloudOptionsFlow:
        """Verification codes are kept in the entry options."""
        return EzvizCloudOptionsFlow()

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


class EzvizCloudOptionsFlow(OptionsFlow):
    """Store the verification code of one camera at a time."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick a camera of the account and type its code; an empty code removes it."""
        codes: dict[str, str] = dict(self.config_entry.options.get(CONF_CODES, {}))
        if user_input is not None:
            code = user_input.get(CONF_CODE, "").strip().upper()
            if code:
                codes[user_input[CONF_SERIAL]] = code
            else:
                codes.pop(user_input[CONF_SERIAL], None)
            return self.async_create_entry(data={**self.config_entry.options, CONF_CODES: codes})

        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        manager = self.config_entry.runtime_data.manager
        try:
            token = await manager.async_get_token()
            cameras = await manager.api.async_get_cameras(token.token)
        except EzvizCloudError:
            return self.async_abort(reason="cannot_connect")
        if not cameras:
            return self.async_abort(reason="no_cameras")
        # One entry per device: a multi-channel device shares a single code.
        devices: dict[str, Camera] = {}
        for camera in cameras:
            devices.setdefault(camera.serial, camera)
        options = [
            SelectOptionDict(
                value=c.serial,
                label=f"{c.name} ({c.serial})" + (" ✓" if c.serial in codes else ""),
            )
            for c in devices.values()
        ]
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERIAL, default=options[0]["value"]): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                    ),
                    vol.Optional(CONF_CODE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
        )
