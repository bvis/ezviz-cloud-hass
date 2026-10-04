"""ezviz_cloud/token websocket command."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState

from custom_components.ezviz_cloud.api import AccessToken, EzvizCloudError
from custom_components.ezviz_cloud.websocket import async_register_commands, ws_get_token

EXPIRY = datetime(2026, 10, 11, tzinfo=UTC)


def _entry(entry_id: str, state: ConfigEntryState = ConfigEntryState.LOADED) -> MagicMock:
    entry = MagicMock(entry_id=entry_id, state=state)
    entry.runtime_data.api.domain = "https://ieuopen.ezvizlife.com"
    entry.runtime_data.async_get_token = AsyncMock(return_value=AccessToken("at.x", EXPIRY))
    return entry


async def _call(entries: list[MagicMock], msg: dict) -> MagicMock:
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = entries
    connection = MagicMock()
    ws_get_token(hass, connection, {"id": 1, "type": "ezviz_cloud/token", **msg})
    await hass.async_create_background_task.call_args.args[0]
    return connection


async def test_returns_token_of_the_only_loaded_entry() -> None:
    conn = await _call([_entry("a", ConfigEntryState.SETUP_ERROR), _entry("b")], {})
    conn.send_result.assert_called_once_with(
        1,
        {
            "access_token": "at.x",
            "domain": "https://ieuopen.ezvizlife.com",
            "expires_at": EXPIRY.isoformat(),
        },
    )


async def test_picks_requested_entry() -> None:
    first, second = _entry("a"), _entry("b")
    await _call([first, second], {"entry_id": "b"})
    first.runtime_data.async_get_token.assert_not_awaited()
    second.runtime_data.async_get_token.assert_awaited_once()


async def test_errors_without_loaded_entry() -> None:
    conn = await _call([], {})
    assert conn.send_error.call_args.args[:2] == (1, "not_found")


async def test_reports_token_failure() -> None:
    entry = _entry("a")
    entry.runtime_data.async_get_token = AsyncMock(side_effect=EzvizCloudError("down"))
    conn = await _call([entry], {})
    assert conn.send_error.call_args.args[:2] == (1, "token_error")


def test_registers_command() -> None:
    hass = MagicMock()
    with patch("custom_components.ezviz_cloud.websocket.async_register_command") as register:
        async_register_commands(hass)
    register.assert_called_once_with(hass, ws_get_token)
