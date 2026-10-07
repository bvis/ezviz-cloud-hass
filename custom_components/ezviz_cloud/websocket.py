"""Websocket commands the card uses: a playable token and the camera list."""

from __future__ import annotations

from typing import Any

import probatio as vol
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import async_response, websocket_command
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .api import Camera, EzvizCloudError
from .const import CONF_CODES, DATA_RECORDER, DOMAIN, MODE_RECORD


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the integration's websocket commands."""
    async_register_command(hass, ws_get_token)
    async_register_command(hass, ws_get_devices)
    async_register_command(hass, ws_recording_start)
    async_register_command(hass, ws_recording_stop)


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
    manager = entry.runtime_data.manager
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
        manager = entry.runtime_data.manager
        codes = entry.options.get(CONF_CODES, {})
        try:
            token = await manager.async_get_token()
            cameras = await manager.api.async_get_cameras(token.token)
        except EzvizCloudError as err:
            connection.send_error(msg["id"], "api_error", str(err))
            return
        schedule_reload_if_new(hass, entry, cameras)
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


def schedule_reload_if_new(hass: HomeAssistant, entry: ConfigEntry, cameras: list[Camera]) -> None:
    """Reload the account when a camera list shows a camera it has no entities for."""
    known = {c.serial for c in entry.runtime_data.cameras}
    if any(c.serial not in known for c in cameras):
        hass.config_entries.async_schedule_reload(entry.entry_id)


def _entry_for_serial(hass: HomeAssistant, serial: str) -> ConfigEntry | None:
    return next(
        (
            e
            for e in _loaded_entries(hass)
            if any(c.serial == serial for c in e.runtime_data.cameras)
        ),
        None,
    )


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/recording/start",
        vol.Required("serial"): str,
        vol.Optional("manual", default=False): bool,
    }
)
@callback
def ws_recording_start(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Open an upload session if nobody is recording the camera.

    On its own the card only records in record mode; `manual` is the user pressing
    Record during the live view, whatever the mode.
    """
    entry = _entry_for_serial(hass, msg["serial"])
    session_id = None
    if entry is not None and (
        msg.get("manual") or entry.runtime_data.modes.get(msg["serial"]) == MODE_RECORD
    ):
        session_id = hass.data[DATA_RECORDER].start(msg["serial"])
    connection.send_result(msg["id"], {"session_id": session_id})


@websocket_command(
    {vol.Required("type"): f"{DOMAIN}/recording/stop", vol.Required("session_id"): str}
)
@async_response
async def ws_recording_stop(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Close an upload session and keep what arrived."""
    await hass.data[DATA_RECORDER].stop(msg["session_id"])
    connection.send_result(msg["id"])
