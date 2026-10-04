"""ezviz_cloud/token and ezviz_cloud/devices websocket commands."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.ezviz_cloud.api import AccessToken, Camera, EzvizCloudError
from custom_components.ezviz_cloud.const import DATA_RECORDER
from custom_components.ezviz_cloud.websocket import (
    async_register_commands,
    ws_get_devices,
    ws_get_token,
    ws_recording_start,
    ws_recording_stop,
)

EXPIRY = datetime(2026, 10, 11, tzinfo=UTC)


def _entry(
    entry_id: str, state: ConfigEntryState = ConfigEntryState.LOADED, codes: dict | None = None
) -> MagicMock:
    entry = MagicMock(entry_id=entry_id, state=state, options={"codes": codes or {}})
    entry.runtime_data.manager.api.domain = "https://ieuopen.ezvizlife.com"
    entry.runtime_data.manager.async_get_token = AsyncMock(return_value=AccessToken("at.x", EXPIRY))
    return entry


async def _call(entries: list[MagicMock], msg: dict, handler=ws_get_token) -> MagicMock:  # type: ignore[no-untyped-def]
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = entries
    connection = MagicMock()
    handler(hass, connection, {"id": 1, **msg})
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
    first.runtime_data.manager.async_get_token.assert_not_awaited()
    second.runtime_data.manager.async_get_token.assert_awaited_once()


async def test_errors_without_loaded_entry() -> None:
    conn = await _call([], {})
    assert conn.send_error.call_args.args[:2] == (1, "not_found")


async def test_reports_token_failure() -> None:
    entry = _entry("a")
    entry.runtime_data.manager.async_get_token = AsyncMock(side_effect=EzvizCloudError("down"))
    conn = await _call([entry], {})
    assert conn.send_error.call_args.args[:2] == (1, "token_error")


def test_registers_command() -> None:
    hass = MagicMock()
    with patch("custom_components.ezviz_cloud.websocket.async_register_command") as register:
        async_register_commands(hass)
    assert [c.args for c in register.call_args_list] == [
        (hass, ws_get_token),
        (hass, ws_get_devices),
        (hass, ws_recording_start),
        (hass, ws_recording_stop),
    ]


async def test_token_includes_stored_code_from_the_account_that_has_it() -> None:
    first, second = _entry("a"), _entry("b", codes={"BK1": "ABCDEF"})
    conn = await _call([first, second], {"serial": "BK1"})
    assert conn.send_result.call_args.args[1]["code"] == "ABCDEF"
    first.runtime_data.manager.async_get_token.assert_not_awaited()


async def test_token_without_stored_code_has_no_code() -> None:
    conn = await _call([_entry("a", codes={"OTHER": "X"})], {"serial": "BK1"})
    assert "code" not in conn.send_result.call_args.args[1]


async def test_devices_lists_cameras_of_every_account() -> None:
    entry = _entry("a", codes={"BK1": "ABCDEF"})
    entry.runtime_data.manager.api.async_get_cameras = AsyncMock(
        return_value=[Camera("BK1", 1, "Door", True), Camera("BK2", 1, "Yard", False)]
    )
    conn = await _call([entry, _entry("b", ConfigEntryState.SETUP_ERROR)], {}, ws_get_devices)
    entry.runtime_data.manager.api.async_get_cameras.assert_awaited_once_with("at.x")
    conn.send_result.assert_called_once_with(
        1,
        [
            {
                "entry_id": "a",
                "serial": "BK1",
                "channel": 1,
                "name": "Door",
                "encrypted": True,
                "has_code": True,
            },
            {
                "entry_id": "a",
                "serial": "BK2",
                "channel": 1,
                "name": "Yard",
                "encrypted": False,
                "has_code": False,
            },
        ],
    )


async def test_devices_reports_api_failure() -> None:
    entry = _entry("a")
    entry.runtime_data.manager.api.async_get_cameras = AsyncMock(
        side_effect=EzvizCloudError("down")
    )
    conn = await _call([entry], {}, ws_get_devices)
    assert conn.send_error.call_args.args[:2] == (1, "api_error")


def _rec_hass(entries: list[MagicMock], sessions: MagicMock) -> MagicMock:
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = entries
    hass.data = {DATA_RECORDER: sessions}
    return hass


def _rec_entry(mode: str = "record") -> MagicMock:
    entry = _entry("a")
    entry.runtime_data.cameras = [Camera("BK1", 1, "Door", True)]
    entry.runtime_data.modes = {"BK1": mode}
    return entry


def test_start_opens_session_in_record_mode() -> None:
    sessions = MagicMock()
    sessions.start.return_value = "sid"
    conn = MagicMock()
    ws_recording_start(
        _rec_hass([_rec_entry()], sessions), conn, {"id": 1, "type": "x", "serial": "BK1"}
    )
    conn.send_result.assert_called_once_with(1, {"session_id": "sid"})


@pytest.mark.parametrize(("mode", "serial"), [("view", "BK1"), ("record", "UNKNOWN")])
def test_start_without_recording(mode: str, serial: str) -> None:
    sessions = MagicMock()
    conn = MagicMock()
    ws_recording_start(
        _rec_hass([_rec_entry(mode)], sessions), conn, {"id": 1, "type": "x", "serial": serial}
    )
    conn.send_result.assert_called_once_with(1, {"session_id": None})
    sessions.start.assert_not_called()


def test_start_returns_null_when_busy() -> None:
    sessions = MagicMock()
    sessions.start.return_value = None
    conn = MagicMock()
    ws_recording_start(
        _rec_hass([_rec_entry()], sessions), conn, {"id": 1, "type": "x", "serial": "BK1"}
    )
    conn.send_result.assert_called_once_with(1, {"session_id": None})


async def _run(handler, hass: MagicMock, msg: dict) -> MagicMock:  # type: ignore[no-untyped-def]
    conn = MagicMock()
    handler(hass, conn, {"id": 1, "type": "x", **msg})
    await hass.async_create_background_task.call_args.args[0]
    return conn


async def test_stop_closes_session() -> None:
    sessions = MagicMock()
    sessions.stop = AsyncMock()
    conn = await _run(ws_recording_stop, _rec_hass([], sessions), {"session_id": "sid"})
    sessions.stop.assert_awaited_once_with("sid")
    conn.send_result.assert_called_once_with(1)


def test_manual_start_records_in_view_mode() -> None:
    sessions = MagicMock()
    sessions.start.return_value = "sid"
    conn = MagicMock()
    hass = _rec_hass([_rec_entry("view")], sessions)
    ws_recording_start(hass, conn, {"id": 1, "type": "x", "serial": "BK1", "manual": True})
    conn.send_result.assert_called_once_with(1, {"session_id": "sid"})
    conn = MagicMock()
    ws_recording_start(hass, conn, {"id": 1, "type": "x", "serial": "UNKNOWN", "manual": True})
    conn.send_result.assert_called_once_with(1, {"session_id": None})
