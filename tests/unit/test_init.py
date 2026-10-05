"""Setup: card registration and credential handling."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from custom_components import ezviz_cloud
from custom_components.ezviz_cloud.api import Camera, EzvizCloudAuthError, EzvizCloudError
from custom_components.ezviz_cloud.const import CARD_URL, DATA_RECORDER
from custom_components.ezviz_cloud.recording import RecordingSessions, RecordingUploadView

DATA = {"region": "eu", "app_key": "key", "app_secret": "secret"}


async def test_setup_serves_card_with_content_hash_url() -> None:
    hass = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn: fn())
    hass.config.media_dirs = {"local": "/media"}
    hass.data = {}
    hass.http.register_view = MagicMock()
    with (
        patch.object(ezviz_cloud, "add_extra_js_url") as add_js,
        patch.object(ezviz_cloud, "async_register_commands") as register_ws,
        patch.object(ezviz_cloud, "async_track_time_interval") as track_expire,
        patch.object(ezviz_cloud.RecordingStore, "recover", return_value=2),
    ):
        assert await ezviz_cloud.async_setup(hass, {})
    assert isinstance(hass.data[DATA_RECORDER], RecordingSessions)
    assert isinstance(hass.http.register_view.call_args.args[0], RecordingUploadView)
    assert track_expire.call_args.args[2] == timedelta(seconds=10)
    with patch.object(RecordingSessions, "expire", AsyncMock()) as expire:
        await track_expire.call_args.args[1](None)
    expire.assert_awaited_once()
    (path_cfg,) = hass.http.async_register_static_paths.await_args.args[0]
    assert path_cfg.url_path == CARD_URL
    assert path_cfg.path.endswith("frontend/ezviz-cloud-live-card.js")
    digest = hashlib.sha256(Path(path_cfg.path).read_bytes()).hexdigest()[:12]
    add_js.assert_called_once_with(hass, f"{CARD_URL}?v={digest}")
    register_ws.assert_called_once_with(hass)


CAMERAS = [
    Camera("BK1", 1, "Door", True),
    Camera("BK1", 2, "Door 2", True),
    Camera("BK2", 1, "Yard", False),
]


def _hass() -> MagicMock:
    hass = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    async def run(fn, *args):  # type: ignore[no-untyped-def]
        return fn(*args)

    hass.async_add_executor_job = run
    hass.data = {}
    return hass


async def _setup_entry(
    side_effect: Exception | None = None,
    cameras_effect: Exception | None = None,
    others: list[MagicMock] | None = None,
) -> tuple[MagicMock, MagicMock]:
    hass = _hass()
    hass.config_entries.async_entries.return_value = others or []
    recorder = MagicMock()
    recorder.store.cleanup.return_value = 0
    hass.data[DATA_RECORDER] = recorder
    entry = MagicMock(entry_id="this", data=DATA, options={})
    with (
        patch.object(ezviz_cloud, "async_get_clientsession"),
        patch.object(ezviz_cloud, "EzvizCloudApi"),
        patch.object(ezviz_cloud, "TokenManager") as manager_cls,
        patch.object(ezviz_cloud, "async_track_time_interval") as track,
        patch.object(ezviz_cloud, "async_dispatcher_connect") as connect,
        patch.object(ezviz_cloud, "async_dispatcher_send") as send,
    ):
        manager = manager_cls.return_value
        manager.async_get_token = AsyncMock(
            side_effect=side_effect, return_value=MagicMock(token="at.x")
        )
        manager.api.async_get_cameras = AsyncMock(side_effect=cameras_effect, return_value=CAMERAS)
        assert await ezviz_cloud.async_setup_entry(hass, entry)
        serials = [c.serial for c in entry.runtime_data.cameras]
        assert track.call_args.args[2] == timedelta(hours=24)
        assert [c.args[1] for c in connect.call_args_list] == [
            f"ezviz_cloud_recorded_{s}" for s in serials
        ]
        # Setup cleans every camera; a saved recording cleans only its own camera.
        assert [c.args[0] for c in recorder.store.cleanup.call_args_list] == serials
        send.assert_not_called()
        recorder.store.cleanup.reset_mock()
        # Deleting old recordings refreshes that camera's entities.
        recorder.store.cleanup.return_value = 1
        await connect.call_args_list[-1].args[2]()
        assert [c.args[0] for c in recorder.store.cleanup.call_args_list] == serials[-1:]
        send.assert_called_once_with(hass, f"ezviz_cloud_recorded_{serials[-1]}")
    return hass, entry


async def test_setup_entry_keeps_data_and_forwards_platforms() -> None:
    hass, entry = await _setup_entry()
    data = entry.runtime_data
    assert [c.serial for c in data.cameras] == ["BK1", "BK2"]
    assert data.modes == {"BK1": "view", "BK2": "view"}
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()


async def test_setup_entry_skips_cameras_of_another_account() -> None:
    other = MagicMock(entry_id="other", state=ConfigEntryState.LOADED)
    other.runtime_data.cameras = [Camera("BK1", 1, "Door", True)]
    not_loaded = MagicMock(entry_id="broken", state=ConfigEntryState.SETUP_ERROR)
    _, entry = await _setup_entry(others=[other, not_loaded])
    assert [c.serial for c in entry.runtime_data.cameras] == ["BK2"]


@pytest.mark.parametrize(
    ("kwargs", "raised"),
    [
        ({"side_effect": EzvizCloudAuthError("bad")}, ConfigEntryError),
        ({"side_effect": EzvizCloudError("down")}, ConfigEntryNotReady),
        ({"cameras_effect": EzvizCloudError("down")}, ConfigEntryNotReady),
    ],
)
async def test_setup_entry_errors(kwargs: dict, raised: type[Exception]) -> None:
    with pytest.raises(raised):
        await _setup_entry(**kwargs)


async def test_unload() -> None:
    hass = _hass()
    assert await ezviz_cloud.async_unload_entry(hass, MagicMock())
    hass.config_entries.async_unload_platforms.assert_awaited_once()
