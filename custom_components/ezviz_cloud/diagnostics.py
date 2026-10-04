"""Diagnostics for EZVIZ Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import EzvizCloudConfigEntry
from .const import CONF_APP_KEY, CONF_APP_SECRET, CONF_CODES

TO_REDACT = {CONF_APP_KEY, CONF_APP_SECRET}


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: EzvizCloudConfigEntry
) -> dict[str, Any]:
    """Return the entry without credentials or codes, plus the cached token's expiry."""
    data = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "devices_with_code": sorted(entry.options.get(CONF_CODES, {})),
        "cameras": [
            {"serial": c.serial, "name": c.name, "mode": data.modes.get(c.serial)}
            for c in data.cameras
        ],
        "api_domain": data.manager.api.domain,
        "token_expires_at": data.manager.expires_at,
    }
