"""The per-camera photo and clip buttons: wiring, storage and error handling."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.ezviz_cloud import EzvizCloudData
from custom_components.ezviz_cloud.api import Camera, EzvizCloudError
from custom_components.ezviz_cloud.button import (
    EzvizCloudButton,
    EzvizCloudCapture,
    EzvizCloudCaptureByMode,
    EzvizCloudRecordClip,
    _ffmpeg_binary,
)
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


def _entity(
    hass: MagicMock,
    code: str | None,
    cls: type[EzvizCloudButton] = EzvizCloudCapture,
    lock: asyncio.Lock | None = None,
) -> EzvizCloudButton:
    options = {CONF_CODES: {"BK1": code}} if code is not None else {}
    entry = MagicMock(runtime_data=_data(), options=options)
    entity = cls(entry.runtime_data, CAM, entry, lock or asyncio.Lock())
    entity.hass = hass
    return entity


async def test_setup_adds_photo_clip_and_by_mode_buttons_per_camera() -> None:
    entry = MagicMock(runtime_data=_data(), options={})
    add = MagicMock()
    await setup_button(MagicMock(), entry, add)
    (entities,) = add.call_args.args
    assert [type(e) for e in entities] == [
        EzvizCloudCapture,
        EzvizCloudRecordClip,
        EzvizCloudCaptureByMode,
    ]
    assert [e.unique_id for e in entities] == ["BK1_capture", "BK1_record", "BK1_capture_by_mode"]
    assert entities[0]._streaming is entities[1]._streaming
    assert entities[2]._buttons == {"photo": entities[0], "record": entities[1]}


def _pipeline(capture: AsyncMock | None = None):  # type: ignore[no-untyped-def]
    """Patch the capture pipeline; returns the patches in order."""
    return (
        patch(
            "custom_components.ezviz_cloud.button.async_capture_ps",
            capture or AsyncMock(return_value=b"ps-bytes"),
        ),
        patch(
            "custom_components.ezviz_cloud.button.decrypt_ps",
            return_value=(b"clear-ps", "hevc"),
        ),
        patch(
            "custom_components.ezviz_cloud.button.async_ps_to_jpeg",
            AsyncMock(return_value=b"\xff\xd8jpeg"),
        ),
        patch(
            "custom_components.ezviz_cloud.button.async_ps_to_mp4",
            AsyncMock(return_value=b"mp4-bytes"),
        ),
        patch(
            "custom_components.ezviz_cloud.button._ffmpeg_binary", return_value="/usr/bin/ffmpeg"
        ),
        patch("custom_components.ezviz_cloud.button.async_get_clientsession"),
        patch("custom_components.ezviz_cloud.button.async_dispatcher_send"),
    )


async def test_photo_press_captures_and_saves_photo(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), "SECRET")
    p_capture, p_decrypt, p_jpeg, p_mp4, p_bin, p_session, p_dispatch = _pipeline()
    with (
        p_capture as capture,
        p_decrypt as decrypt,
        p_jpeg as to_jpeg,
        p_mp4 as to_mp4,
        p_bin,
        p_session,
        p_dispatch as dispatch,
    ):
        await entity.async_press()

    entity._data.manager.api.async_live_url.assert_awaited_once_with("tok", "BK1", 1, "SECRET")
    assert capture.await_args.args[1] == "wss://vtm/live?dev=BK1"
    decrypt.assert_called_once_with(b"ps-bytes", "SECRET")
    assert to_jpeg.await_args.args == (b"clear-ps", "/usr/bin/ffmpeg")
    to_mp4.assert_not_awaited()
    folder = tmp_path / "ezviz_cloud" / "BK1"
    assert [p.read_bytes() for p in folder.iterdir()] == [b"\xff\xd8jpeg"]
    dispatch.assert_called_once()


async def test_clip_press_saves_video_and_photo(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), "SECRET", EzvizCloudRecordClip)
    p_capture, p_decrypt, p_jpeg, p_mp4, p_bin, p_session, p_dispatch = _pipeline()
    with p_capture as capture, p_decrypt, p_jpeg, p_mp4 as to_mp4, p_bin, p_session, p_dispatch:
        await entity.async_press()

    # 15 s by default, plus the 3 s clear start that is skipped.
    assert capture.await_args.kwargs["capture_seconds"] == 18
    assert capture.await_args.kwargs["max_bytes"] == 18 * 700_000
    assert to_mp4.await_args.args == (b"clear-ps", "hevc", "/usr/bin/ffmpeg")
    folder = tmp_path / "ezviz_cloud" / "BK1"
    (video,) = folder.glob("*.mp4")
    (photo,) = folder.glob("*.jpg")
    assert video.read_bytes() == b"mp4-bytes"
    assert photo.read_bytes() == b"\xff\xd8jpeg"
    assert video.stem == photo.stem
    assert not list(folder.glob("*.part"))


async def test_press_without_code_passes_none(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), None)
    p_capture, p_decrypt, p_jpeg, p_mp4, p_bin, p_session, p_dispatch = _pipeline()
    with p_capture, p_decrypt as decrypt, p_jpeg, p_mp4, p_bin, p_session, p_dispatch:
        await entity.async_press()
    assert entity._data.manager.api.async_live_url.await_args.args[3] is None
    assert decrypt.call_args.args[1] is None


async def test_press_while_the_other_button_streams_is_ignored(tmp_path: Path) -> None:
    lock = asyncio.Lock()
    photo = _entity(_hass(tmp_path), "SECRET", EzvizCloudCapture, lock)
    clip = _entity(_hass(tmp_path), "SECRET", EzvizCloudRecordClip, lock)
    release = asyncio.Event()

    async def slow_capture(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        await release.wait()
        return b"ps"

    capture = AsyncMock(side_effect=slow_capture)
    p_capture, p_decrypt, p_jpeg, p_mp4, p_bin, p_session, p_dispatch = _pipeline(capture)
    with p_capture, p_decrypt, p_jpeg, p_mp4, p_bin, p_session, p_dispatch:
        first = asyncio.create_task(clip.async_press())
        await asyncio.sleep(0)
        await photo.async_press()
        await clip.async_press()
        release.set()
        await first
    assert capture.await_count == 1


@pytest.mark.parametrize(
    ("cls", "what"), [(EzvizCloudCapture, "photo"), (EzvizCloudRecordClip, "clip")]
)
async def test_press_wraps_capture_errors(
    tmp_path: Path, cls: type[EzvizCloudButton], what: str
) -> None:
    entity = _entity(_hass(tmp_path), "SECRET", cls)
    p_capture, p_decrypt, p_jpeg, p_mp4, p_bin, p_session, p_dispatch = _pipeline(
        AsyncMock(side_effect=EzvizCloudError("asleep"))
    )
    with (
        p_capture,
        p_decrypt,
        p_jpeg,
        p_mp4,
        p_bin,
        p_session,
        p_dispatch as dispatch,
        pytest.raises(HomeAssistantError, match=f"{what} of BK1: asleep"),
    ):
        await entity.async_press()
    dispatch.assert_not_called()


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


async def test_clip_follows_the_cameras_clip_length(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), "SECRET", EzvizCloudRecordClip)
    entity._data.clip_seconds["BK1"] = 60
    p_capture, p_decrypt, p_jpeg, p_mp4, p_bin, p_session, p_dispatch = _pipeline()
    with p_capture as capture, p_decrypt, p_jpeg, p_mp4, p_bin, p_session, p_dispatch:
        await entity.async_press()
    assert capture.await_args.kwargs["capture_seconds"] == 63


@pytest.mark.parametrize(
    ("mode", "pressed", "last"),
    [("view", None, "none"), ("photo", "photo", "photo"), ("record", "clip", "clip")],
)
async def test_capture_by_mode_presses_what_the_mode_says(
    mode: str, pressed: str | None, last: str
) -> None:
    data = _data()
    data.modes["BK1"] = mode
    photo, clip = MagicMock(_what="photo"), MagicMock(_what="clip")
    photo.async_press = AsyncMock()
    clip.async_press = AsyncMock()
    entity = EzvizCloudCaptureByMode(data, CAM, photo, clip)
    entity.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    assert entity.extra_state_attributes == {"last_capture": None}

    await entity.async_press()

    assert photo.async_press.await_count == (pressed == "photo")
    assert clip.async_press.await_count == (pressed == "clip")
    assert entity.extra_state_attributes == {"last_capture": last}
    entity.async_write_ha_state.assert_called_once()
