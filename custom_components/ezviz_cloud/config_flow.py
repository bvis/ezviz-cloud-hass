"""Config flow: an EZVIZ Open Platform app (region, AppKey, AppSecret) or the EZVIZ app
account the official EZVIZ integration is logged in with."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from typing import Any

import probatio as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .account import EZVIZ_CLOUD_ACCOUNT, EZVIZ_DOMAIN
from .api import Camera, EzvizCloudApi, EzvizCloudAuthError, EzvizCloudError
from .const import (
    CONF_ACCOUNT,
    CONF_APP_KEY,
    CONF_APP_SECRET,
    CONF_CODE,
    CONF_CODES,
    CONF_MAX_PER_CAMERA,
    CONF_NEW_TOKEN,
    CONF_REGION,
    CONF_RETENTION_DAYS,
    CONF_SERIAL,
    CONF_STREAM_TOKEN,
    DEFAULT_MAX_PER_CAMERA,
    DEFAULT_RETENTION_DAYS,
    DOMAIN,
    REGIONS,
)
from .live import LiveStream, async_grab_jpeg
from .snapshot import EzvizCloudDecodeError
from .websocket import schedule_reload_if_new

_LOGGER = logging.getLogger(__name__)

SECRET_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

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
        vol.Required(CONF_APP_SECRET): SECRET_SELECTOR,
    }
)


class EzvizCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pick where video comes from: an Open Platform app or the EZVIZ app account."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(_entry: ConfigEntry) -> EzvizCloudOptionsFlow:
        """Verification codes are kept in the entry options."""
        return EzvizCloudOptionsFlow()

    async def _async_check(self, region: str, app_key: str, app_secret: str) -> dict[str, str]:
        """Ask the platform for a token; the errors to show, empty when it worked."""
        api = EzvizCloudApi(
            async_get_clientsession(self.hass), REGIONS[region], app_key, app_secret
        )
        try:
            await api.async_get_token()
        except EzvizCloudAuthError:
            return {"base": "invalid_auth"}
        except EzvizCloudError:
            return {"base": "cannot_connect"}
        return {}

    async def async_step_user(self, _user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Open Platform app or EZVIZ app account."""
        return self.async_show_menu(step_id="user", menu_options=["open_platform", "app_account"])

    async def async_step_reconfigure(
        self, _user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The same choice; switching keeps the codes, recordings and stream addresses."""
        return self.async_show_menu(
            step_id="reconfigure", menu_options=["open_platform", "app_account"]
        )

    async def async_step_open_platform(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the region and the app's credentials."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry() if self.source == SOURCE_RECONFIGURE else None
        if user_input is not None:
            data = _clean(user_input)
            await self.async_set_unique_id(data[CONF_APP_KEY])
            if entry is not None and CONF_APP_KEY in entry.data:
                # Same kind: only the region or the secret of the same app can change.
                self._abort_if_unique_id_mismatch()
            else:
                self._abort_if_taken(entry)
            errors = await self._async_check(**data)
            if not errors:
                return self._finish(entry, _title(data), data)
        suggested = user_input
        if suggested is None and entry is not None:
            suggested = {k: v for k, v in entry.data.items() if k != CONF_APP_SECRET}
        return self.async_show_form(
            step_id="open_platform",
            data_schema=self.add_suggested_values_to_schema(DATA_SCHEMA, suggested),
            errors=errors,
        )

    async def async_step_app_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick an account the official EZVIZ integration is logged in with."""
        accounts = {
            e.unique_id: e.title
            for e in self.hass.config_entries.async_entries(EZVIZ_DOMAIN)
            if e.data.get("type") == EZVIZ_CLOUD_ACCOUNT
            and e.unique_id
            and e.state is ConfigEntryState.LOADED
        }
        if not accounts:
            return self.async_abort(reason="no_ezviz_account")
        entry = self._get_reconfigure_entry() if self.source == SOURCE_RECONFIGURE else None
        if user_input is not None and user_input[CONF_ACCOUNT] in accounts:
            account = user_input[CONF_ACCOUNT]
            await self.async_set_unique_id(f"ezviz_app_{account}")
            self._abort_if_taken(entry)
            return self._finish(
                entry, f"EZVIZ Cloud ({accounts[account]})", {CONF_ACCOUNT: account}
            )
        return self.async_show_form(
            step_id="app_account",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT, default=next(iter(accounts))): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=uid, label=title)
                                for uid, title in accounts.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    def _abort_if_taken(self, entry: ConfigEntry | None) -> None:
        """Abort when another entry already uses the flow's unique id."""
        if entry is None:
            self._abort_if_unique_id_configured()
            return
        for other in self._async_current_entries(include_ignore=False):
            if other.entry_id != entry.entry_id and other.unique_id == self.unique_id:
                raise AbortFlow("already_configured")

    def _finish(
        self, entry: ConfigEntry | None, title: str, data: dict[str, str]
    ) -> ConfigFlowResult:
        if entry is None:
            return self.async_create_entry(title=title, data=data)
        return self.async_update_reload_and_abort(
            entry, unique_id=self.unique_id, title=title, data=data
        )

    async def async_step_reauth(self, _entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """EZVIZ rejected the stored credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the AppSecret again; region and AppKey stay."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_APP_SECRET: user_input[CONF_APP_SECRET].strip()}
            errors = await self._async_check(**data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_APP_SECRET): SECRET_SELECTOR}),
            description_placeholders={"app_key": entry.data[CONF_APP_KEY]},
            errors=errors,
        )


def _clean(user_input: dict[str, Any]) -> dict[str, str]:
    """The entry data from a form, credentials trimmed."""
    return {
        CONF_REGION: user_input[CONF_REGION],
        CONF_APP_KEY: user_input[CONF_APP_KEY].strip(),
        CONF_APP_SECRET: user_input[CONF_APP_SECRET].strip(),
    }


def _title(data: dict[str, str]) -> str:
    return f"EZVIZ Cloud ({data[CONF_REGION].upper()})"


class EzvizCloudOptionsFlow(OptionsFlow):
    """Store the verification code of one camera at a time."""

    async def async_step_codes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick a camera of the account and type its code; an empty code removes it."""
        codes: dict[str, str] = dict(self.config_entry.options.get(CONF_CODES, {}))
        errors: dict[str, str] = {}
        if user_input is not None:
            code = user_input.get(CONF_CODE, "").strip().upper()
            if code and not await self._code_works(user_input[CONF_SERIAL], code):
                errors["base"] = "invalid_code"
            else:
                if code:
                    codes[user_input[CONF_SERIAL]] = code
                else:
                    codes.pop(user_input[CONF_SERIAL], None)
                return self.async_create_entry(
                    data={**self.config_entry.options, CONF_CODES: codes}
                )

        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        try:
            cameras = await self.config_entry.runtime_data.account.async_cameras()
        except EzvizCloudError:
            return self.async_abort(reason="cannot_connect")
        if not cameras:
            return self.async_abort(reason="no_cameras")
        schedule_reload_if_new(self.hass, self.config_entry, cameras)
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
            step_id="codes",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SERIAL,
                        default=(user_input or {}).get(CONF_SERIAL, options[0]["value"]),
                    ): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                    ),
                    vol.Optional(CONF_CODE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
        )

    async def _code_works(self, serial: str, code: str) -> bool:
        """Decode one keyframe of the camera with ``code``; only a frame that won't
        decode fails it. A camera that doesn't answer, or that is already streaming
        with the current code, is saved unchecked. Requests to EZVIZ: one stream."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return True
        data = self.config_entry.runtime_data
        stream = data.streams.get(serial)
        if stream is None or stream.active:
            return True
        probe = LiveStream(self.hass, data.account, stream.camera, lambda: code)
        try:
            await async_grab_jpeg(self.hass, probe)
        except EzvizCloudDecodeError:
            return False
        except EzvizCloudError as err:
            _LOGGER.debug("Code of %s saved unchecked: %s", serial, err)
        finally:
            await probe.async_close()
        return True

    async def async_step_init(self, _user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Each part saves on its own, so changing one never resets the others."""
        return self.async_show_menu(step_id="init", menu_options=["codes", "recordings", "stream"])

    async def async_step_recordings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """How long recordings are kept."""
        options = self.config_entry.options
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **options,
                    CONF_RETENTION_DAYS: int(user_input[CONF_RETENTION_DAYS]),
                    CONF_MAX_PER_CAMERA: int(user_input[CONF_MAX_PER_CAMERA]),
                }
            )
        return self.async_show_form(
            step_id="recordings",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RETENTION_DAYS,
                        default=options.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS),
                    ): NumberSelector(
                        NumberSelectorConfig(min=1, max=90, step=1, mode=NumberSelectorMode.BOX)
                    ),
                    vol.Required(
                        CONF_MAX_PER_CAMERA,
                        default=options.get(CONF_MAX_PER_CAMERA, DEFAULT_MAX_PER_CAMERA),
                    ): NumberSelector(
                        NumberSelectorConfig(min=0, max=1000, step=1, mode=NumberSelectorMode.BOX)
                    ),
                }
            ),
        )

    async def async_step_stream(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The live stream addresses for other apps (go2rtc, Frigate); a new token voids them."""
        entry = self.config_entry
        if user_input is not None:
            if not user_input.get(CONF_NEW_TOKEN):
                return self.async_create_entry(data=dict(entry.options))
            token = secrets.token_urlsafe(24)
            if entry.state is ConfigEntryState.LOADED:
                for stream in entry.runtime_data.streams.values():
                    stream.token = token
            return self.async_create_entry(data={**entry.options, CONF_STREAM_TOKEN: token})
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        try:
            base = get_url(self.hass, allow_external=False)
        except NoURLAvailableError:
            base = "http://HOME_ASSISTANT_IP:8123"
        token = entry.options.get(CONF_STREAM_TOKEN, "")
        urls = "\n".join(
            f"- {c.name}: `{base}/api/{DOMAIN}/live/{c.serial}?token={token}`"
            for c in entry.runtime_data.cameras
        )
        return self.async_show_form(
            step_id="stream",
            description_placeholders={"urls": urls},
            data_schema=vol.Schema(
                {vol.Optional(CONF_NEW_TOKEN, default=False): BooleanSelector()}
            ),
        )
