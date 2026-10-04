"""Websocket commands the card uses: a playable token and the camera list."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import async_response, websocket_command
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .api import EzvizCloudError
from .const import CONF_CODES, DOMAIN


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the integration's websocket commands."""
    async_register_command(hass, ws_get_token)
    async_register_command(hass, ws_get_devices)


def _loaded_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED
    ]


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/token",
        vol.Optional("entry_id"): str,
        vol.Optional("serial"): str,
    }
)
@async_response
async def ws_get_token(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return an access token and API domain, plus the camera's stored code if any.

    With a serial, the account that holds a code for it wins, so a card only
    needs the serial even when several accounts are set up.
    """
    entries = [e for e in _loaded_entries(hass) if msg.get("entry_id") in (None, e.entry_id)]
    if not entries:
        connection.send_error(msg["id"], "not_found", "No loaded EZVIZ Cloud account")
        return
    serial = msg.get("serial")
    entry = next((e for e in entries if serial in e.options.get(CONF_CODES, {})), entries[0])
    manager = entry.runtime_data
    try:
        token = await manager.async_get_token()
    except EzvizCloudError as err:
        connection.send_error(msg["id"], "token_error", str(err))
        return
    result = {
        "access_token": token.token,
        "domain": manager.api.domain,
        "expires_at": token.expires_at.isoformat(),
    }
    if code := entry.options.get(CONF_CODES, {}).get(serial):
        result["code"] = code
    connection.send_result(msg["id"], result)


@websocket_command({vol.Required("type"): f"{DOMAIN}/devices"})
@async_response
async def ws_get_devices(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """List the cameras of every loaded account, for the card editor."""
    devices = []
    for entry in _loaded_entries(hass):
        manager = entry.runtime_data
        codes = entry.options.get(CONF_CODES, {})
        try:
            token = await manager.async_get_token()
            cameras = await manager.api.async_get_cameras(token.token)
        except EzvizCloudError as err:
            connection.send_error(msg["id"], "api_error", str(err))
            return
        devices += [
            {
                "entry_id": entry.entry_id,
                "serial": c.serial,
                "channel": c.channel,
                "name": c.name,
                "encrypted": c.encrypted,
                "has_code": c.serial in codes,
            }
            for c in cameras
        ]
    connection.send_result(msg["id"], devices)
