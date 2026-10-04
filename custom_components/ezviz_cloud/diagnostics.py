"""Diagnostics for EZVIZ Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import EzvizCloudConfigEntry
from .const import CONF_APP_KEY, CONF_APP_SECRET

TO_REDACT = {CONF_APP_KEY, CONF_APP_SECRET}


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: EzvizCloudConfigEntry
) -> dict[str, Any]:
    """Return the entry without credentials, plus the cached token's expiry."""
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "api_domain": entry.runtime_data.api.domain,
        "token_expires_at": entry.runtime_data.expires_at,
    }
