"""Media source: cameras at the root, their recordings newest first."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from homeassistant.components.media_player.const import MediaClass
from homeassistant.components.media_source import MediaSourceItem, Unresolvable
from homeassistant.util import dt as dt_util

from custom_components.ezviz_cloud import EzvizCloudData
from custom_components.ezviz_cloud.api import Camera
from custom_components.ezviz_cloud.const import DATA_RECORDER
from custom_components.ezviz_cloud.media_source import async_get_media_source
from custom_components.ezviz_cloud.recording import RecordingStore

WHEN = datetime(2026, 10, 18, 15, 35, 10, tzinfo=dt_util.get_default_time_zone())


@pytest.fixture
def store(tmp_path: Path) -> RecordingStore:
    return RecordingStore(tmp_path)


@pytest.fixture
def hass(store: RecordingStore) -> MagicMock:
    hass = MagicMock()
    hass.data = {DATA_RECORDER: MagicMock(store=store)}
    entry = MagicMock(
        runtime_data=EzvizCloudData(MagicMock(), [Camera("BK1", 1, "Door", True)], {})
    )
    hass.config_entries.async_loaded_entries.return_value = [entry]

    async def run(fn, *args):  # type: ignore[no-untyped-def]
        return fn(*args)

    hass.async_add_executor_job = run
    return hass


def _item(hass: MagicMock, identifier: str | None) -> MediaSourceItem:
    return MediaSourceItem(hass, "ezviz_cloud", identifier or "", None)


def _clip(store: RecordingStore, serial: str, when: datetime) -> str:
    stem = store.stem_for(when)
    part = store.video_part(serial, stem, "mp4")
    store.append(part, b"x")
    store.finalize(part)
    store.save_photo(store.photo_path(serial, stem), b"\xff\xd8")
    return stem


async def test_root_lists_cameras_by_name(hass: MagicMock, store: RecordingStore) -> None:
    source = await async_get_media_source(hass)
    root = await source.async_browse_media(_item(hass, None))
    assert root.title == "EZVIZ Cloud"
    assert root.children == []
    _clip(store, "BK1", WHEN)
    _clip(store, "OLD9", WHEN)
    root = await source.async_browse_media(_item(hass, None))
    # A camera gone from the account still shows, by serial.
    assert [(c.identifier, c.title) for c in root.children or []] == [
        ("BK1", "Door"),
        ("OLD9", "OLD9"),
    ]


async def test_camera_lists_clips_and_photos(hass: MagicMock, store: RecordingStore) -> None:
    clip = _clip(store, "BK1", WHEN)
    photo = store.stem_for(WHEN + timedelta(minutes=1))
    store.save_photo(store.photo_path("BK1", photo), b"\xff\xd8")
    source = await async_get_media_source(hass)
    folder = await source.async_browse_media(_item(hass, "BK1"))
    assert folder.title == "Door"
    newest, oldest = folder.children or []
    assert (newest.identifier, newest.media_class, newest.title) == (
        f"BK1/{photo}.jpg",
        MediaClass.IMAGE,
        "2026-10-18 15:36:10",
    )
    assert (oldest.identifier, oldest.media_class) == (f"BK1/{clip}.mp4", MediaClass.VIDEO)
    assert oldest.thumbnail == f"/media/local/ezviz_cloud/BK1/{clip}.jpg"

    played = await source.async_resolve_media(_item(hass, oldest.identifier))
    assert (played.url, played.mime_type) == (
        f"/media/local/ezviz_cloud/BK1/{clip}.mp4",
        "video/mp4",
    )
    played = await source.async_resolve_media(_item(hass, newest.identifier))
    assert played.mime_type == "image/jpeg"


@pytest.mark.parametrize(
    "identifier",
    ["", "BK1", "BK1/2026-10-18_15-35-10.mp4", "BK1/../secret.jpg", "../x/a.jpg", "BK1/notes.txt"],
)
async def test_resolve_rejects_anything_not_listed(hass: MagicMock, identifier: str) -> None:
    source = await async_get_media_source(hass)
    with pytest.raises(Unresolvable):
        await source.async_resolve_media(_item(hass, identifier))


async def test_browse_rejects_unsafe_serial(hass: MagicMock) -> None:
    source = await async_get_media_source(hass)
    with pytest.raises(Unresolvable):
        await source.async_browse_media(_item(hass, "../etc"))
