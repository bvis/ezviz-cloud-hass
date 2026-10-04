"""EZVIZ Cloud: live view of EZVIZ cameras through the EZVIZ Open Platform."""

from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import EzvizCloudApi, EzvizCloudAuthError, EzvizCloudError
from .const import (
    CARD_FILENAME,
    CARD_URL,
    CONF_APP_KEY,
    CONF_APP_SECRET,
    CONF_REGION,
    DOMAIN,
    REGIONS,
)
from .token import TokenManager
from .websocket import async_register_commands

type EzvizCloudConfigEntry = ConfigEntry[TokenManager]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Serve the bundled Lovelace card and register the websocket command."""
    card = Path(__file__).parent / "frontend" / CARD_FILENAME
    content = await hass.async_add_executor_job(card.read_bytes)
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card), True)])
    # The file is served with a month-long cache, so the URL carries a hash of its
    # content: any change to the card reaches browsers on the next page load.
    add_extra_js_url(hass, f"{CARD_URL}?v={hashlib.sha256(content).hexdigest()[:12]}")
    async_register_commands(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EzvizCloudConfigEntry) -> bool:
    """Validate the credentials once and keep a token manager for the card."""
    api = EzvizCloudApi(
        async_get_clientsession(hass),
        REGIONS[entry.data[CONF_REGION]],
        entry.data[CONF_APP_KEY],
        entry.data[CONF_APP_SECRET],
    )
    manager = TokenManager(api)
    try:
        await manager.async_get_token()
    except EzvizCloudAuthError as err:
        raise ConfigEntryError(f"EZVIZ rejected the appKey/appSecret: {err}") from err
    except EzvizCloudError as err:
        raise ConfigEntryNotReady(str(err)) from err
    entry.runtime_data = manager
    return True


async def async_unload_entry(_hass: HomeAssistant, _entry: EzvizCloudConfigEntry) -> bool:
    """Nothing to tear down: the manager holds no connections."""
    return True
