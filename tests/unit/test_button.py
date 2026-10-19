"""The per-camera photo and clip buttons: reading the shared stream, storage, errors."""

from __future__ import annotations

import asyncio
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
)
from custom_components.ezviz_cloud.button import async_setup_entry as setup_button
from custom_components.ezviz_cloud.const import DATA_RECORDER
from custom_components.ezviz_cloud.recording import RecordingStore

CAM = Camera("BK1", 1, "Door", True)
STREAM = MagicMock(codec="hevc")


def _data() -> EzvizCloudData:
    data = EzvizCloudData(MagicMock(), [CAM], {"BK1": "view"})
    data.streams["BK1"] = STREAM
    return data


def _hass(tmp_path: Path) -> MagicMock:
    hass = MagicMock()
    hass.data = {DATA_RECORDER: MagicMock(store=RecordingStore(tmp_path))}

    async def run(fn, *args):  # type: ignore[no-untyped-def]
        return fn(*args)

    hass.async_add_executor_job = run
    return hass


def _entity(
    hass: MagicMock,
    cls: type[EzvizCloudButton] = EzvizCloudCapture,
    lock: asyncio.Lock | None = None,
) -> EzvizCloudButton:
    entity = cls(_data(), CAM, lock or asyncio.Lock())
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


def _pipeline(read: AsyncMock | None = None, grab: AsyncMock | None = None):  # type: ignore[no-untyped-def]
    """Patch the shared stream readers and ffmpeg; returns the patches in order."""
    return (
        patch(
            "custom_components.ezviz_cloud.button.async_grab_jpeg",
            grab or AsyncMock(return_value=b"\xff\xd8grab"),
        ),
        patch(
            "custom_components.ezviz_cloud.button.async_read",
            read or AsyncMock(return_value=b"clear-ps"),
        ),
        patch(
            "custom_components.ezviz_cloud.button.async_ps_to_jpeg",
            AsyncMock(return_value=b"\xff\xd8jpeg"),
        ),
        patch(
            "custom_components.ezviz_cloud.button.async_ps_to_mp4",
            AsyncMock(return_value=b"mp4-bytes"),
        ),
        patch("custom_components.ezviz_cloud.button.ffmpeg_binary", return_value="/usr/bin/ffmpeg"),
        patch("custom_components.ezviz_cloud.button.async_dispatcher_send"),
    )


async def test_photo_press_grabs_from_the_shared_stream(tmp_path: Path) -> None:
    hass = _hass(tmp_path)
    entity = _entity(hass)
    p_grab, p_read, p_jpeg, p_mp4, p_bin, p_dispatch = _pipeline()
    with p_grab as grab, p_read as read, p_jpeg, p_mp4 as to_mp4, p_bin, p_dispatch as dispatch:
        await entity.async_press()

    grab.assert_awaited_once_with(hass, STREAM)
    read.assert_not_awaited()
    to_mp4.assert_not_awaited()
    folder = tmp_path / "ezviz_cloud" / "BK1"
    assert [p.read_bytes() for p in folder.iterdir()] == [b"\xff\xd8grab"]
    dispatch.assert_called_once()


async def test_clip_press_saves_video_and_photo(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), EzvizCloudRecordClip)
    p_grab, p_read, p_jpeg, p_mp4, p_bin, p_dispatch = _pipeline()
    with p_grab, p_read as read, p_jpeg as to_jpeg, p_mp4 as to_mp4, p_bin, p_dispatch:
        await entity.async_press()

    # 15 s by default.
    read.assert_awaited_once_with(STREAM, 15, 15 * 700_000)
    assert to_mp4.await_args.args == (b"clear-ps", "hevc", "/usr/bin/ffmpeg")
    assert to_jpeg.await_args.args == (b"clear-ps", "/usr/bin/ffmpeg")
    folder = tmp_path / "ezviz_cloud" / "BK1"
    (video,) = folder.glob("*.mp4")
    (photo,) = folder.glob("*.jpg")
    assert video.read_bytes() == b"mp4-bytes"
    assert photo.read_bytes() == b"\xff\xd8jpeg"
    assert video.stem == photo.stem
    assert not list(folder.glob("*.part"))


async def test_press_while_the_other_button_captures_is_ignored(tmp_path: Path) -> None:
    lock = asyncio.Lock()
    photo = _entity(_hass(tmp_path), EzvizCloudCapture, lock)
    clip = _entity(_hass(tmp_path), EzvizCloudRecordClip, lock)
    release = asyncio.Event()

    async def slow_read(*_args):  # type: ignore[no-untyped-def]
        await release.wait()
        return b"ps"

    read = AsyncMock(side_effect=slow_read)
    p_grab, p_read, p_jpeg, p_mp4, p_bin, p_dispatch = _pipeline(read)
    with p_grab as grab, p_read, p_jpeg, p_mp4, p_bin, p_dispatch:
        first = asyncio.create_task(clip.async_press())
        await asyncio.sleep(0)
        await photo.async_press()
        await clip.async_press()
        release.set()
        await first
    assert read.await_count == 1
    grab.assert_not_awaited()


@pytest.mark.parametrize(
    ("cls", "what"), [(EzvizCloudCapture, "photo"), (EzvizCloudRecordClip, "clip")]
)
async def test_press_wraps_capture_errors(
    tmp_path: Path, cls: type[EzvizCloudButton], what: str
) -> None:
    entity = _entity(_hass(tmp_path), cls)
    failing = AsyncMock(side_effect=EzvizCloudError("asleep"))
    p_grab, p_read, p_jpeg, p_mp4, p_bin, p_dispatch = _pipeline(failing, failing)
    with (
        p_grab,
        p_read,
        p_jpeg,
        p_mp4,
        p_bin,
        p_dispatch as dispatch,
        pytest.raises(HomeAssistantError, match=f"{what} of BK1: asleep"),
    ):
        await entity.async_press()
    dispatch.assert_not_called()


async def test_clip_follows_the_cameras_clip_length(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), EzvizCloudRecordClip)
    entity._data.clip_seconds["BK1"] = 60
    p_grab, p_read, p_jpeg, p_mp4, p_bin, p_dispatch = _pipeline()
    with p_grab, p_read as read, p_jpeg, p_mp4, p_bin, p_dispatch:
        await entity.async_press()
    assert read.await_args.args[1] == 60


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
