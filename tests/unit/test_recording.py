"""Recording storage, upload sessions and the upload view."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.http import KEY_HASS
from homeassistant.util import dt as dt_util

from custom_components.ezviz_cloud.const import DATA_RECORDER
from custom_components.ezviz_cloud.recording import (
    RecordingSessions,
    RecordingStore,
    RecordingUploadView,
    SessionNotFoundError,
    SessionTooLargeError,
    UnsupportedTypeError,
)

NOW = datetime(2026, 10, 4, 22, 0, 0, tzinfo=dt_util.get_default_time_zone())


def _make(
    store: RecordingStore, serial: str, when: datetime, video: bool = True, photo: bool = True
) -> str:
    stem = store.stem_for(when)
    if video:
        part = store.video_part(serial, stem, "mp4")
        store.append(part, b"data")
        store.finalize(part)
    if photo:
        store.save_photo(store.photo_path(serial, stem), b"\xff\xd8")
    return stem


def test_paths_and_names(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    stem = store.stem_for(NOW)
    assert stem == "2026-10-04_22-00-00"
    assert (
        store.video_part("BK1", stem, "mp4")
        == tmp_path / "ezviz_cloud/BK1/2026-10-04_22-00-00.mp4.part"
    )
    assert store.photo_path("BK1", stem) == tmp_path / "ezviz_cloud/BK1/2026-10-04_22-00-00.jpg"


@pytest.mark.parametrize("serial", ["../etc", "BK1/..", "", "a b"])
def test_rejects_unsafe_serial(tmp_path: Path, serial: str) -> None:
    with pytest.raises(ValueError, match="Unsafe serial"):
        RecordingStore(tmp_path).photo_path(serial, "2026-10-04_22-00-00")


def test_append_and_finalize(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    part = store.video_part("BK1", "2026-10-04_22-00-00", "mp4")
    store.append(part, b"ab")
    store.append(part, b"cd")
    final = store.finalize(part)
    assert final == part.with_suffix("")
    assert final is not None
    assert final.read_bytes() == b"abcd"
    assert not part.exists()


def test_finalize_empty_or_missing_part(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    part = store.video_part("BK1", "2026-10-04_22-00-00", "mp4")
    assert store.finalize(part) is None
    part.touch()
    assert store.finalize(part) is None
    assert not part.exists()


def test_recordings_newest_first_and_latest(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    old = _make(store, "BK1", NOW - timedelta(hours=1), photo=False)
    new = _make(store, "BK1", NOW)
    (tmp_path / "ezviz_cloud/BK1/notes.txt").write_text("ignored")
    (tmp_path / "ezviz_cloud/BK1/snapshot.jpg").write_bytes(b"not a recording")
    store.video_part("BK1", store.stem_for(NOW + timedelta(minutes=1)), "mp4").write_bytes(b"x")
    recs = store.recordings("BK1")
    assert [r.stem for r in recs] == [new, old]
    assert recs[0].started == NOW
    assert recs[0].video is not None
    assert recs[0].photo is not None
    assert recs[1].photo is None
    assert store.latest("BK1") == recs[0]
    assert store.latest("OTHER") is None


def test_recover_renames_parts(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    part = store.video_part("BK1", "2026-10-04_22-00-00", "webm")
    part.write_bytes(b"x")
    assert store.recover() == 1
    assert (tmp_path / "ezviz_cloud/BK1/2026-10-04_22-00-00.webm").exists()
    assert RecordingStore(tmp_path / "empty").recover() == 0


def test_cleanup_by_age_and_count(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    stems = [_make(store, "BK1", NOW - timedelta(days=d)) for d in (0, 1, 2, 20)]
    removed = store.cleanup("BK1", retention_days=10, max_count=2, now=NOW)
    assert removed == 2
    assert [r.stem for r in store.recordings("BK1")] == stems[:2]
    assert len(os.listdir(tmp_path / "ezviz_cloud/BK1")) == 4  # two videos + two photos


def test_cleanup_without_count_limit(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    for d in range(5):
        _make(store, "BK1", NOW - timedelta(days=d))
    assert store.cleanup("BK1", retention_days=10, max_count=0, now=NOW) == 0
    assert store.cleanup("BK1", retention_days=1, max_count=0, now=NOW) == 3


def test_uri(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    path = store.photo_path("BK1", "2026-10-04_22-00-00")
    assert (
        store.uri(path)
        == "media-source://media_source/local/ezviz_cloud/BK1/2026-10-04_22-00-00.jpg"
    )


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _sessions(tmp_path: Path) -> tuple[RecordingSessions, _Clock, MagicMock]:
    hass = MagicMock()

    async def run(fn, *args):  # type: ignore[no-untyped-def]
        return fn(*args)

    hass.async_add_executor_job = run
    clock = _Clock()
    return RecordingSessions(hass, RecordingStore(tmp_path), clock), clock, hass


async def test_session_records_video_and_signals(tmp_path: Path) -> None:
    sessions, _, hass = _sessions(tmp_path)
    with patch("custom_components.ezviz_cloud.recording.dt_util.now", return_value=NOW):
        sid = sessions.start("BK1")
    assert sid
    assert sessions.target(sid) == ("BK1", "2026-10-04_22-00-00")
    await sessions.append(sid, b"ab", "video/mp4;codecs=avc1")
    await sessions.append(sid, b"cd", "video/mp4")
    with patch("custom_components.ezviz_cloud.recording.async_dispatcher_send") as send:
        await sessions.stop(sid)
    send.assert_called_once_with(hass, "ezviz_cloud_recorded_BK1")
    assert (tmp_path / "ezviz_cloud/BK1/2026-10-04_22-00-00.mp4").read_bytes() == b"abcd"
    with pytest.raises(SessionNotFoundError):
        sessions.target(sid)


async def test_only_one_session_per_serial(tmp_path: Path) -> None:
    sessions, _, _ = _sessions(tmp_path)
    first = sessions.start("BK1")
    assert sessions.start("BK1") is None
    assert sessions.start("BK2")
    with patch("custom_components.ezviz_cloud.recording.async_dispatcher_send"):
        await sessions.stop(first)  # type: ignore[arg-type]
    assert sessions.start("BK1")


async def test_append_errors(tmp_path: Path) -> None:
    sessions, _, _ = _sessions(tmp_path)
    with pytest.raises(SessionNotFoundError):
        await sessions.append("nope", b"x", "video/mp4")
    sid = sessions.start("BK1")
    with pytest.raises(UnsupportedTypeError):
        await sessions.append(sid, b"x", "text/html")  # type: ignore[arg-type]
    with (
        patch("custom_components.ezviz_cloud.recording.MAX_SESSION_BYTES", 3),
        patch("custom_components.ezviz_cloud.recording.async_dispatcher_send"),
    ):
        await sessions.append(sid, b"ab", "video/webm")  # type: ignore[arg-type]
        with pytest.raises(SessionTooLargeError):
            await sessions.append(sid, b"cd", "video/webm")  # type: ignore[arg-type]
    assert sessions.start("BK1")  # the oversized session was closed
    assert len(list((tmp_path / "ezviz_cloud/BK1").glob("*.webm"))) == 1


async def test_expire_closes_idle_session(tmp_path: Path) -> None:
    sessions, clock, _ = _sessions(tmp_path)
    sid = sessions.start("BK1")
    await sessions.append(sid, b"ab", "video/mp4")  # type: ignore[arg-type]
    clock.now += 29
    with patch("custom_components.ezviz_cloud.recording.async_dispatcher_send") as send:
        await sessions.expire()
        send.assert_not_called()
        clock.now += 2
        await sessions.expire()
        send.assert_called_once()
    assert len(list((tmp_path / "ezviz_cloud/BK1").glob("*.mp4"))) == 1


async def test_photo_and_stop_without_video(tmp_path: Path) -> None:
    sessions, _, _ = _sessions(tmp_path)
    sid = sessions.start("BK1")
    serial, stem = sessions.target(sid)  # type: ignore[arg-type]
    with patch("custom_components.ezviz_cloud.recording.async_dispatcher_send") as send:
        await sessions.save_photo(serial, stem, b"\xff\xd8")
        await sessions.stop(sid)  # type: ignore[arg-type]
        await sessions.stop(sid)  # type: ignore[arg-type]  # second stop is a no-op
    assert send.call_count == 2
    assert [p.suffix for p in (tmp_path / "ezviz_cloud/BK1").iterdir()] == [".jpg"]


def _request(
    sessions: MagicMock, body: bytes = b"ab", ctype: str = "video/mp4", length: int | None = 2
) -> MagicMock:
    request = MagicMock()
    request.app = {KEY_HASS: MagicMock(data={DATA_RECORDER: sessions})}
    request.content_type = ctype
    request.content_length = length
    request.read = AsyncMock(return_value=body)
    return request


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (None, 200),
        (SessionNotFoundError("x"), 404),
        (SessionTooLargeError("x"), 413),
        (UnsupportedTypeError("x"), 415),
        (OSError("disk full"), 500),
    ],
)
async def test_upload_view_maps_errors(exc: Exception | None, status: int) -> None:
    sessions = MagicMock()
    sessions.append = AsyncMock(side_effect=exc)
    resp = await RecordingUploadView().post(_request(sessions), "sid")
    assert resp.status == status
    sessions.append.assert_awaited_once_with("sid", b"ab", "video/mp4")


async def test_upload_unknown_session_404(tmp_path: Path) -> None:
    sessions, _, _ = _sessions(tmp_path)
    resp = await RecordingUploadView().post(_request(sessions), "made-up")  # type: ignore[arg-type]
    assert resp.status == 404
    assert not (tmp_path / "ezviz_cloud").exists()


async def test_upload_rejects_huge_chunk_before_reading() -> None:
    sessions = MagicMock()
    request = _request(sessions, length=9 * 1024 * 1024)
    resp = await RecordingUploadView().post(request, "sid")
    assert resp.status == 413
    request.read.assert_not_awaited()


def test_upload_view_needs_auth() -> None:
    view = RecordingUploadView()
    assert view.requires_auth is True
    assert view.url == "/api/ezviz_cloud/recording/{session_id}"


async def test_slow_wake_keeps_session_until_first_chunk(tmp_path: Path) -> None:
    sessions, clock, _ = _sessions(tmp_path)
    sid = sessions.start("BK1")
    clock.now += 35  # camera still waking: no chunk yet
    with patch("custom_components.ezviz_cloud.recording.async_dispatcher_send"):
        await sessions.expire()
        assert sessions.start("BK1") is None
        await sessions.append(sid, b"ab", "video/mp4")  # type: ignore[arg-type]
        clock.now += 121
        await sessions.expire()
    assert sessions.start("BK1")


async def test_session_without_chunks_expires_eventually(tmp_path: Path) -> None:
    sessions, clock, _ = _sessions(tmp_path)
    sessions.start("BK1")
    clock.now += 121
    with patch("custom_components.ezviz_cloud.recording.async_dispatcher_send"):
        await sessions.expire()
    assert sessions.start("BK1")


def test_finalize_never_replaces_a_finished_video(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    part = store.video_part("BK1", "2026-10-04_22-00-00", "mp4")
    store.append(part, b"good")
    final = store.finalize(part)
    store.append(part, b"stray fragment")  # a late write after the session closed
    assert store.finalize(part) is None
    assert final is not None
    assert final.read_bytes() == b"good"
    assert not part.exists()
    part.write_bytes(b"stray")
    assert store.recover() == 0
    assert final.read_bytes() == b"good"


async def test_add_photo_saves_jpg_and_signals(tmp_path: Path) -> None:
    sessions, _, hass = _sessions(tmp_path)
    with patch("custom_components.ezviz_cloud.recording.dt_util.now", return_value=NOW):
        sid = sessions.start("BK1")
    with patch("custom_components.ezviz_cloud.recording.async_dispatcher_send") as send:
        await sessions.add_photo(sid, b"\xff\xd8frame")  # type: ignore[arg-type]
    send.assert_called_once_with(hass, "ezviz_cloud_recorded_BK1")
    assert (tmp_path / "ezviz_cloud/BK1/2026-10-04_22-00-00.jpg").read_bytes() == b"\xff\xd8frame"
    with pytest.raises(SessionNotFoundError):
        await sessions.add_photo("nope", b"x")


async def test_upload_view_routes_photos() -> None:
    sessions = MagicMock()
    sessions.append = AsyncMock()
    sessions.add_photo = AsyncMock()
    resp = await RecordingUploadView().post(_request(sessions, b"jpg", "image/jpeg"), "sid")
    assert resp.status == 200
    sessions.add_photo.assert_awaited_once_with("sid", b"jpg")
    sessions.append.assert_not_awaited()
