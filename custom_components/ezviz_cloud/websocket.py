"""Websocket command the card uses to get a playable token."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import async_response, websocket_command
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .api import EzvizCloudError
from .const import DOMAIN


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the integration's websocket commands."""
    async_register_command(hass, ws_get_token)


@websocket_command({vol.Required("type"): f"{DOMAIN}/token", vol.Optional("entry_id"): str})
@async_response
async def ws_get_token(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return an access token and API domain for the requested (or only) account."""
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED and msg.get("entry_id") in (None, e.entry_id)
    ]
    if not entries:
        connection.send_error(msg["id"], "not_found", "No loaded EZVIZ Cloud account")
        return
    manager = entries[0].runtime_data
    try:
        token = await manager.async_get_token()
    except EzvizCloudError as err:
        connection.send_error(msg["id"], "token_error", str(err))
        return
    connection.send_result(
        msg["id"],
        {
            "access_token": token.token,
            "domain": manager.api.domain,
            "expires_at": token.expires_at.isoformat(),
        },
    )
