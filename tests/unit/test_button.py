"""The per-camera capture button: wiring, storage and error handling."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.ezviz_cloud import EzvizCloudData
from custom_components.ezviz_cloud.api import Camera, EzvizCloudError
from custom_components.ezviz_cloud.button import EzvizCloudCapture
from custom_components.ezviz_cloud.button import async_setup_entry as setup_button
from custom_components.ezviz_cloud.const import CONF_CODES, DATA_RECORDER
from custom_components.ezviz_cloud.recording import RecordingStore

CAM = Camera("BK1", 1, "Door", True)


def _data() -> EzvizCloudData:
    manager = MagicMock()
    manager.api.domain = "https://d"
    manager.async_get_token = AsyncMock(return_value=MagicMock(token="tok"))
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


async def test_press_captures_and_saves_photo(tmp_path: Path) -> None:
    hass = _hass(tmp_path)
    entity = _entity(hass, "SECRET")
    with (
        patch(
            "custom_components.ezviz_cloud.button.async_capture_ps",
            AsyncMock(return_value=b"ps-bytes"),
        ) as capture,
        patch(
            "custom_components.ezviz_cloud.button.decrypt_and_demux", return_value=b"annexb"
        ) as demux,
        patch(
            "custom_components.ezviz_cloud.button.async_annexb_to_jpeg",
            AsyncMock(return_value=b"\xff\xd8jpeg"),
        ) as to_jpeg,
        patch(
            "custom_components.ezviz_cloud.button._ffmpeg_binary", return_value="/usr/bin/ffmpeg"
        ),
        patch("custom_components.ezviz_cloud.button.async_get_clientsession"),
        patch("custom_components.ezviz_cloud.button.async_dispatcher_send") as dispatch,
    ):
        await entity.async_press()

    assert capture.await_args.args[2:6] == ("tok", "BK1", 1, "SECRET")
    demux.assert_called_once_with(b"ps-bytes", "SECRET")
    assert to_jpeg.await_args.args[0] == b"annexb"
    saved = list((tmp_path / "ezviz_cloud" / "BK1").glob("*.jpg"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"\xff\xd8jpeg"
    dispatch.assert_called_once()


async def test_press_without_code_passes_none(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), None)
    with (
        patch(
            "custom_components.ezviz_cloud.button.async_capture_ps",
            AsyncMock(return_value=b"ps"),
        ) as capture,
        patch("custom_components.ezviz_cloud.button.decrypt_and_demux", return_value=b"annexb"),
        patch(
            "custom_components.ezviz_cloud.button.async_annexb_to_jpeg",
            AsyncMock(return_value=b"jpg"),
        ),
        patch(
            "custom_components.ezviz_cloud.button._ffmpeg_binary", return_value="/usr/bin/ffmpeg"
        ),
        patch("custom_components.ezviz_cloud.button.async_get_clientsession"),
        patch("custom_components.ezviz_cloud.button.async_dispatcher_send"),
    ):
        await entity.async_press()
    assert capture.await_args.args[5] is None


async def test_press_wraps_capture_errors(tmp_path: Path) -> None:
    entity = _entity(_hass(tmp_path), "SECRET")
    with (
        patch(
            "custom_components.ezviz_cloud.button.async_capture_ps",
            AsyncMock(side_effect=EzvizCloudError("asleep")),
        ),
        patch("custom_components.ezviz_cloud.button.async_get_clientsession"),
        pytest.raises(HomeAssistantError, match="asleep"),
    ):
        await entity.async_press()
