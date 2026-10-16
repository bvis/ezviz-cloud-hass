"""The per-camera capture button: wiring, storage and error handling."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.ezviz_cloud import EzvizCloudData
from custom_components.ezviz_cloud.api import Camera, EzvizCloudError
from custom_components.ezviz_cloud.button import EzvizCloudCapture, _ffmpeg_binary
from custom_components.ezviz_cloud.button import async_setup_entry as setup_button
from custom_components.ezviz_cloud.const import CONF_CODES, DATA_RECORDER
from custom_components.ezviz_cloud.recording import RecordingStore

CAM = Camera("BK1", 1, "Door", True)


def _data() -> EzvizCloudData:
    manager = MagicMock()
    manager.api.domain = "https://d"
    manager.async_get_token = AsyncMock(return_value=MagicMock(token="tok"))
    manager.api.async_live_url = AsyncMock(return_value="wss://vtm/live?dev=BK1")
    return EzvizCloudData(manager, [CAM], {"BK1": "view"})


def _hass(tmp_path: Path) -> MagicMock:
    hass = MagicMock()
    hass.data = {DATA_RECORDER: MagicMock(store=RecordingStore(tmp_path))}

    async def run(fn, *args):  # type: ignore[no-untyped-def]
        return fn(*args)

    hass.async_add_executor_job = run
    return hass


def _entity(hass: MagicMock, code: str | None) -> EzvizCloudCapture:
    options = {CONF_CODES: {"BK1": code}} if code is not None else {}
    entry = MagicMock(runtime_data=_data(), options=options)
    entity = EzvizCloudCapture(entry.runtime_data, CAM, entry)
    entity.hass = hass
    return entity


async def test_setup_adds_one_button_per_camera() -> None:
    entry = MagicMock(runtime_data=_data(), options={})
    add = MagicMock()
    await setup_button(MagicMock(), entry, add)
    (entities,) = add.call_args.args
    assert [type(e) for e in entities] == [EzvizCloudCapture]
    assert entities[0].unique_id == "BK1_capture"


def _pipeline(capture: AsyncMock | None = None):  # type: ignore[no-untyped-def]
    """Patch the capture pipeline; returns the patches in order."""
    return (
        patch(
            "custom_components.ezviz_cloud.button.async_capture_ps",
            capture or AsyncMock(return_value=b"ps-bytes"),
        ),
        patch(
            "custom_components.ezviz_cloud.button.decrypt_and_demux",
            return_value=(b"annexb", "h264"),
        ),
        patch(
            "custom_components.ezviz_cloud.button.async_annexb_to_jpeg",
            AsyncMock(return_value=b"\xff\xd8jpeg"),
        ),
        patch(
            "custom_components.ezviz_cloud.button._ffmpeg_binary", return_value="/usr/bin/ffmpeg"
        ),
        patch("custom_components.ezviz_cloud.button.async_get_clientsession"),
        patch("custom_components.ezviz_cloud.button.async_dispatcher_send"),
    )


async def test_press_captures_and_saves_photo(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), "SECRET")
    p_capture, p_demux, p_jpeg, p_bin, p_session, p_dispatch = _pipeline()
    with (
        p_capture as capture,
        p_demux as demux,
        p_jpeg as to_jpeg,
        p_bin,
        p_session,
        p_dispatch as dispatch,
    ):
        await entity.async_press()

    entity._data.manager.api.async_live_url.assert_awaited_once_with("tok", "BK1", 1, "SECRET")
    assert capture.await_args.args[1] == "wss://vtm/live?dev=BK1"
    demux.assert_called_once_with(b"ps-bytes", "SECRET")
    assert to_jpeg.await_args.args[:2] == (b"annexb", "h264")
    saved = list((tmp_path / "ezviz_cloud" / "BK1").glob("*.jpg"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"\xff\xd8jpeg"
    dispatch.assert_called_once()


async def test_press_without_code_passes_none(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), None)
    p_capture, p_demux, p_jpeg, p_bin, p_session, p_dispatch = _pipeline()
    with p_capture, p_demux as demux, p_jpeg, p_bin, p_session, p_dispatch:
        await entity.async_press()
    assert entity._data.manager.api.async_live_url.await_args.args[3] is None
    assert demux.call_args.args[1] is None


async def test_press_while_capturing_is_ignored(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), "SECRET")
    release = asyncio.Event()

    async def slow_capture(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        await release.wait()
        return b"ps"

    capture = AsyncMock(side_effect=slow_capture)
    p_capture, p_demux, p_jpeg, p_bin, p_session, p_dispatch = _pipeline(capture)
    with p_capture, p_demux, p_jpeg, p_bin, p_session, p_dispatch:
        first = asyncio.create_task(entity.async_press())
        await asyncio.sleep(0)
        await entity.async_press()
        release.set()
        await first
    assert capture.await_count == 1


async def test_press_wraps_capture_errors(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), "SECRET")
    p_capture, p_demux, p_jpeg, p_bin, p_session, p_dispatch = _pipeline(
        AsyncMock(side_effect=EzvizCloudError("asleep"))
    )
    with (
        p_capture,
        p_demux,
        p_jpeg,
        p_bin,
        p_session,
        p_dispatch,
        pytest.raises(HomeAssistantError, match="asleep"),
    ):
        await entity.async_press()


async def test_press_wraps_token_errors(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), "SECRET")
    entity._data.manager.async_get_token = AsyncMock(side_effect=EzvizCloudError("no token"))
    with pytest.raises(HomeAssistantError, match="no token"):
        await entity.async_press()


def test_ffmpeg_binary_comes_from_ha_ffmpeg_manager() -> None:
    fake = MagicMock()
    fake.get_ffmpeg_manager.return_value.binary = "/opt/ffmpeg"
    with patch.dict(sys.modules, {"homeassistant.components.ffmpeg": fake}):
        assert _ffmpeg_binary(MagicMock()) == "/opt/ffmpeg"
