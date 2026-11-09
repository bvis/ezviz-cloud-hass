"""Diagnostics for EZVIZ Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import EzvizCloudConfigEntry
from .account import OpenPlatformAccount
from .const import CONF_APP_KEY, CONF_APP_SECRET, CONF_CODES

TO_REDACT = {CONF_APP_KEY, CONF_APP_SECRET}


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: EzvizCloudConfigEntry
) -> dict[str, Any]:
    """Return the entry without credentials or codes, plus the cached token's expiry."""
    data = entry.runtime_data
    source: dict[str, Any] = {"source": "ezviz_app"}
    if isinstance(account := data.account, OpenPlatformAccount):
        source = {
            "source": "open_platform",
            "api_domain": account.manager.api.domain,
            "token_expires_at": account.manager.expires_at,
        }
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "devices_with_code": sorted(entry.options.get(CONF_CODES, {})),
        "cameras": [
            {"serial": c.serial, "name": c.name, "mode": data.modes.get(c.serial)}
            for c in data.cameras
        ],
        **source,
    }
