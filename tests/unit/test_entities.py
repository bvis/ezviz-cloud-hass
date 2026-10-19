"""Per-camera entities: mode select, clip length, last photo camera, last recording sensor."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.camera.const import CameraEntityFeature
from homeassistant.util import dt as dt_util

from custom_components.ezviz_cloud import EzvizCloudData
from custom_components.ezviz_cloud.api import Camera
from custom_components.ezviz_cloud.camera import EzvizCloudLastPhoto, EzvizCloudLive
from custom_components.ezviz_cloud.camera import async_setup_entry as setup_camera
from custom_components.ezviz_cloud.const import DATA_RECORDER
from custom_components.ezviz_cloud.number import EzvizCloudClipLength
from custom_components.ezviz_cloud.number import async_setup_entry as setup_number
from custom_components.ezviz_cloud.recording import RecordingStore
from custom_components.ezviz_cloud.select import EzvizCloudMode
from custom_components.ezviz_cloud.select import async_setup_entry as setup_select
from custom_components.ezviz_cloud.sensor import EzvizCloudLastRecording
from custom_components.ezviz_cloud.sensor import async_setup_entry as setup_sensor

CAM = Camera("BK1", 1, "Door", True)
WHEN = datetime(2026, 10, 4, 22, 0, tzinfo=dt_util.get_default_time_zone())


def _data() -> EzvizCloudData:
    return EzvizCloudData(MagicMock(), [CAM], {"BK1": "view"})


def _hass(tmp_path: Path) -> MagicMock:
    hass = MagicMock()
    store = RecordingStore(tmp_path)
    hass.data = {DATA_RECORDER: MagicMock(store=store)}

    async def run(fn, *args):  # type: ignore[no-untyped-def]
        return fn(*args)

    hass.async_add_executor_job = run
    return hass


async def test_platforms_add_one_entity_per_camera() -> None:
    entry = MagicMock(runtime_data=_data())
    for setup, cls in (
        (setup_select, EzvizCloudMode),
        (setup_number, EzvizCloudClipLength),
        (setup_camera, (EzvizCloudLastPhoto, EzvizCloudLive)),
        (setup_sensor, EzvizCloudLastRecording),
    ):
        add = MagicMock()
        await setup(MagicMock(), entry, add)
        (entities,) = add.call_args.args
        assert [type(e) for e in entities] == list(cls if isinstance(cls, tuple) else (cls,))


def test_device_and_ids() -> None:
    entity = EzvizCloudMode(_data(), CAM)
    assert entity.unique_id == "BK1_mode"
    assert entity.device_info == {
        "identifiers": {("ezviz_cloud", "BK1"), ("ezviz", "BK1")},
        "name": "Door",
        "manufacturer": "EZVIZ",
        "serial_number": "BK1",
    }


async def test_select_restores_and_changes_mode() -> None:
    data = _data()
    entity = EzvizCloudMode(data, CAM)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    with patch.object(
        EzvizCloudMode, "async_get_last_state", AsyncMock(return_value=MagicMock(state="record"))
    ):
        await entity.async_added_to_hass()
    assert data.modes["BK1"] == "record"
    assert entity.current_option == "record"
    await entity.async_select_option("view")
    assert data.modes["BK1"] == "view"
    entity.async_write_ha_state.assert_called_once()


async def test_select_ignores_unknown_restored_state() -> None:
    data = _data()
    entity = EzvizCloudMode(data, CAM)
    entity.hass = MagicMock()
    with patch.object(
        EzvizCloudMode,
        "async_get_last_state",
        AsyncMock(return_value=MagicMock(state="unavailable")),
    ):
        await entity.async_added_to_hass()
    assert data.modes["BK1"] == "view"


async def test_select_offers_view_photo_and_record() -> None:
    assert EzvizCloudMode(_data(), CAM).options == ["view", "photo", "record"]


async def test_clip_length_defaults_restores_and_changes() -> None:
    data = _data()
    entity = EzvizCloudClipLength(data, CAM)
    assert entity.native_value == 15
    assert (entity.native_min_value, entity.native_max_value) == (10, 60)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    with patch.object(
        EzvizCloudClipLength,
        "async_get_last_number_data",
        AsyncMock(return_value=MagicMock(native_value=42.0)),
    ):
        await entity.async_added_to_hass()
    assert data.clip_seconds["BK1"] == 42
    await entity.async_set_native_value(30)
    assert entity.native_value == 30
    entity.async_write_ha_state.assert_called_once()


async def test_clip_length_ignores_missing_or_out_of_range_restore() -> None:
    for restored in (None, MagicMock(native_value=None), MagicMock(native_value=600.0)):
        data = _data()
        entity = EzvizCloudClipLength(data, CAM)
        entity.hass = MagicMock()
        with patch.object(
            EzvizCloudClipLength, "async_get_last_number_data", AsyncMock(return_value=restored)
        ):
            await entity.async_added_to_hass()
        assert data.clip_seconds["BK1"] == 15


async def test_camera_serves_latest_photo(tmp_path: Path) -> None:
    hass = _hass(tmp_path)
    entity = EzvizCloudLastPhoto(_data(), CAM)
    entity.hass = hass
    assert await entity.async_camera_image() is None
    store = hass.data[DATA_RECORDER].store
    store.save_photo(store.photo_path("BK1", store.stem_for(WHEN)), b"\xff\xd8new")
    assert await entity.async_camera_image() == b"\xff\xd8new"


async def test_sensor_reports_latest_recording(tmp_path: Path) -> None:
    hass = _hass(tmp_path)
    store = hass.data[DATA_RECORDER].store
    entity = EzvizCloudLastRecording(_data(), CAM)
    entity.hass = hass
    entity.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    with patch("custom_components.ezviz_cloud.sensor.async_dispatcher_connect") as connect:
        await entity.async_added_to_hass()
    assert connect.call_args.args[1] == "ezviz_cloud_recorded_BK1"
    assert entity.native_value is None
    stem = store.stem_for(WHEN)
    part = store.video_part("BK1", stem, "mp4")
    store.append(part, b"x")
    store.finalize(part)
    await connect.call_args.args[2]()
    assert entity.native_value == WHEN
    assert entity.extra_state_attributes == {
        "video": f"media-source://media_source/local/ezviz_cloud/BK1/{stem}.mp4",
        "photo": None,
    }


@pytest.mark.parametrize(
    ("api", "url"),
    [
        (MagicMock(use_ssl=False, port=8123), "http://127.0.0.1:8123"),
        (MagicMock(use_ssl=True, port=443), "https://127.0.0.1:443"),
        (None, "http://127.0.0.1:8123"),
    ],
)
async def test_live_camera_streams_from_the_local_view(
    tmp_path: Path, api: MagicMock | None, url: str
) -> None:
    data = _data()
    data.streams["BK1"] = MagicMock(token="tok")
    entity = EzvizCloudLive(data, CAM)
    entity.hass = _hass(tmp_path)
    entity.hass.config.api = api
    assert entity.unique_id == "BK1_live"
    assert entity.supported_features & CameraEntityFeature.STREAM
    assert await entity.stream_source() == f"{url}/api/ezviz_cloud/live/BK1?token=tok"
    assert await entity.async_camera_image() is None
