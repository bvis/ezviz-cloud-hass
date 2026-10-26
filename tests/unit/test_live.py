"""The shared live stream: one open per camera, keyframe starts, linger, cooldown, the view."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from custom_components.ezviz_cloud import live
from custom_components.ezviz_cloud.api import Camera, EzvizCloudError
from custom_components.ezviz_cloud.live import (
    EzvizCloudCooldownError,
    LiveStream,
    LiveStreamView,
    async_grab_jpeg,
    async_read,
    ffmpeg_binary,
    find_stream,
)

from .test_snapshot import IMKH, PACK, _gop, _pes

CAM = Camera("BK1", 1, "Door", True)
KEY, FRAME = _gop(b"key"), PACK + _pes(b"p")


def _hass() -> MagicMock:
    hass = MagicMock()
    hass.async_create_background_task = lambda coro, _name: asyncio.create_task(coro)

    async def run(fn, *args):  # type: ignore[no-untyped-def]
        return fn(*args)

    hass.async_add_executor_job = run
    return hass


def _stream(code: str | None = None) -> LiveStream:
    manager = MagicMock()
    manager.async_get_token = AsyncMock(return_value=MagicMock(token="tok"))
    manager.api.async_live_url = AsyncMock(return_value="wss://vtm/live?dev=BK1")
    return LiveStream(_hass(), manager, CAM, lambda: code)


class _Upstream:
    """Stands in for the EZVIZ WebSocket: yields what the test feeds it."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[bytes | Exception | None] = asyncio.Queue()
        self.opens = 0
        self.closed = 0

    async def __call__(self, _session: object, _url: str) -> AsyncIterator[bytes]:
        self.opens += 1
        try:
            while (item := await self.queue.get()) is not None:
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            self.closed += 1


@pytest.fixture
def upstream() -> AsyncIterator[_Upstream]:
    fake = _Upstream()
    with (
        patch.object(live, "async_iter_stream", fake),
        patch.object(live, "async_get_clientsession"),
    ):
        yield fake


async def _take(frames: AsyncIterator[bytes], n: int) -> list[bytes]:
    return [await anext(frames) for _ in range(n)]


async def test_readers_share_one_stream_and_start_at_a_keyframe(upstream: _Upstream) -> None:
    stream = _stream()
    first = stream.frames()
    pending = asyncio.ensure_future(_take(first, 2))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(IMKH + FRAME + KEY + FRAME + PACK)
    # A pack before the first keyframe is never handed out.
    assert await pending == [KEY, FRAME]
    assert stream.active

    second = stream.frames()
    late = asyncio.ensure_future(_take(second, 1))
    await asyncio.sleep(0)
    # The pack left open by the trailing PACK above completes into FRAME.
    upstream.queue.put_nowait(_pes(b"p") + KEY + PACK)
    assert await anext(first) == FRAME
    assert await late == [KEY]  # the second reader waits for the next keyframe
    assert upstream.opens == 1
    stream._manager.api.async_live_url.assert_awaited_once_with("tok", "BK1", 1, None)
    await first.aclose()
    await second.aclose()
    await stream.async_close()


async def test_stream_lingers_after_the_last_reader_then_closes(
    upstream: _Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "LINGER", 0.01)
    stream = _stream()
    async with contextlib.aclosing(stream.frames()) as frames:
        pending = asyncio.ensure_future(anext(frames))
        await asyncio.sleep(0)
        upstream.queue.put_nowait(KEY + PACK)
        assert await pending == KEY
    assert stream.active  # still open: a reader arriving now reuses it
    async with contextlib.aclosing(stream.frames()) as frames:
        pending = asyncio.ensure_future(anext(frames))
        await asyncio.sleep(0)
        upstream.queue.put_nowait(FRAME + KEY + PACK)
        assert await pending == KEY
    assert upstream.opens == 1
    await asyncio.sleep(0.05)
    assert not stream.active
    assert upstream.closed == 1


async def test_linger_stop_without_a_keyframe_cools_down(
    upstream: _Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    # HA's stream worker gave up waiting for a picture and left (#24): its retries
    # must not wake the camera again.
    monkeypatch.setattr(live, "LINGER", 0.01)
    stream = _stream()
    stream.on_no_video = MagicMock()
    frames = stream.frames()
    pending = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(FRAME + PACK)  # packs, but never a keyframe
    await asyncio.sleep(0.01)
    pending.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await pending
    await frames.aclose()
    await asyncio.sleep(0.05)
    assert not stream.active
    assert stream._cooldown_until > 0
    stream.on_no_video.assert_called_once_with()
    with pytest.raises(EzvizCloudCooldownError):
        await anext(stream.frames())
    assert upstream.opens == 1


async def test_linger_stop_after_video_does_not_cool_down(
    upstream: _Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "LINGER", 0.01)
    stream = _stream()
    stream.on_no_video = MagicMock()
    async with contextlib.aclosing(stream.frames()) as frames:
        pending = asyncio.ensure_future(anext(frames))
        await asyncio.sleep(0)
        upstream.queue.put_nowait(KEY + PACK)
        assert await pending == KEY
    await asyncio.sleep(0.05)
    assert not stream.active
    assert stream._cooldown_until == 0
    stream.on_no_video.assert_not_called()


async def test_failed_open_reaches_readers_and_starts_a_cooldown(upstream: _Upstream) -> None:
    stream = _stream()
    upstream.queue.put_nowait(EzvizCloudError("5405"))
    stream.on_no_video = MagicMock()
    with pytest.raises(EzvizCloudError, match="5405"):
        await anext(stream.frames())
    with pytest.raises(EzvizCloudCooldownError, match="a moment ago"):
        await anext(stream.frames())
    assert upstream.opens == 1
    stream.on_no_video.assert_called_once_with()


async def test_stream_without_video_also_cools_down(upstream: _Upstream) -> None:
    stream = _stream()
    upstream.queue.put_nowait(IMKH)
    upstream.queue.put_nowait(None)
    with pytest.raises(EzvizCloudError, match="no video"):
        await anext(stream.frames())
    assert stream._cooldown_until > 0


async def test_stream_that_ends_after_video_ends_its_readers(upstream: _Upstream) -> None:
    stream = _stream()
    frames = stream.frames()
    pending = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(KEY + PACK)
    assert await pending == KEY
    upstream.queue.put_nowait(None)
    with pytest.raises(StopAsyncIteration):
        await anext(frames)
    assert stream._cooldown_until == 0


async def test_close_stops_the_stream_without_a_cooldown(upstream: _Upstream) -> None:
    stream = _stream()
    frames = stream.frames()
    pending = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    await stream.async_close()
    with pytest.raises(StopAsyncIteration):
        await pending
    assert stream._cooldown_until == 0
    assert not stream.active
    await stream.async_close()  # nothing open: no-op


async def test_code_decrypts_and_skips_the_first_group(upstream: _Upstream) -> None:
    stream = _stream("SECRET")
    calls = []

    def fake_decrypt(packs: list[bytes], code: str, codec: str) -> list[bytes]:
        calls.append((code, codec))
        return [p.upper() for p in packs]

    with patch.object(live, "decrypt_packs", fake_decrypt):
        frames = stream.frames()
        pending = asyncio.ensure_future(anext(frames))
        await asyncio.sleep(0)
        upstream.queue.put_nowait(IMKH + _gop(b"stale") + KEY + PACK)
        assert await pending == KEY.upper()
        await frames.aclose()
    assert calls == [("SECRET", "hevc")]
    await stream.async_close()


async def test_a_reader_that_falls_behind_is_dropped(
    upstream: _Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "_MAX_BACKLOG", 2)
    stream = _stream()
    frames = stream.frames()
    pending = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(KEY + FRAME + FRAME + FRAME + PACK)
    with pytest.raises(EzvizCloudError, match="fell behind"):
        await pending
        await _take(frames, 3)
    await stream.async_close()


async def test_read_collects_seconds_of_video(upstream: _Upstream) -> None:
    stream = _stream()
    reading = asyncio.ensure_future(async_read(stream, 0, 1_000_000))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(KEY + FRAME + PACK)
    assert await reading == KEY  # zero seconds: the keyframe only
    await stream.async_close()


async def test_read_stops_at_max_bytes(upstream: _Upstream) -> None:
    stream = _stream()
    reading = asyncio.ensure_future(async_read(stream, 60, 1))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(KEY + FRAME + PACK)
    assert await reading == KEY
    await stream.async_close()


async def test_read_errors(upstream: _Upstream, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "_STALL_MARGIN", 0.01)
    stream = _stream()
    with pytest.raises(EzvizCloudError, match="asleep"):
        await async_read(stream, 0, 10)
    await stream.async_close()

    stream = _stream()
    upstream.queue.put_nowait(KEY)  # a keyframe that never completes, then the end
    upstream.queue.put_nowait(None)
    with pytest.raises(EzvizCloudError, match="no video"):
        await async_read(stream, 5, 10)


async def test_read_keeps_what_arrived_before_a_stall(
    upstream: _Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "_STALL_MARGIN", 0.01)
    stream = _stream()
    reading = asyncio.ensure_future(async_read(stream, 0.05, 1_000_000))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(KEY + PACK)  # then nothing more: the stream stalls
    assert await reading == KEY
    await stream.async_close()


async def test_read_of_a_stream_that_ends_before_a_keyframe(upstream: _Upstream) -> None:
    stream = _stream()
    reading = asyncio.ensure_future(async_read(stream, 60, 1_000_000))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(FRAME + PACK)
    upstream.queue.put_nowait(None)
    # Packs without a keyframe are no video at all.
    with pytest.raises(EzvizCloudError, match="no video"):
        await reading

    # A reader that joins after the keyframe and sees the stream end first.
    stream = _stream()
    async with contextlib.aclosing(stream.frames()) as frames:
        pending = asyncio.ensure_future(anext(frames))
        await asyncio.sleep(0)
        upstream.queue.put_nowait(KEY + PACK)
        assert await pending == KEY
        late = asyncio.ensure_future(async_read(stream, 60, 1_000_000))
        await asyncio.sleep(0)
        upstream.queue.put_nowait(_pes(b"p") + FRAME + PACK)
        upstream.queue.put_nowait(None)
        with pytest.raises(EzvizCloudError, match="before its first keyframe"):
            await late


async def test_read_ends_with_the_stream(upstream: _Upstream) -> None:
    stream = _stream()
    reading = asyncio.ensure_future(async_read(stream, 60, 1_000_000))
    await asyncio.sleep(0)
    upstream.queue.put_nowait(KEY + PACK)
    upstream.queue.put_nowait(None)
    assert await reading == KEY


async def test_grab_jpeg_decodes_the_first_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    read = AsyncMock(return_value=b"ps")
    to_jpeg = AsyncMock(return_value=b"\xff\xd8")
    monkeypatch.setattr(live, "async_read", read)
    monkeypatch.setattr(live, "async_ps_to_jpeg", to_jpeg)
    monkeypatch.setattr(live, "ffmpeg_binary", lambda _hass: "/ffmpeg")
    stream = MagicMock()
    assert await async_grab_jpeg(MagicMock(), stream) == b"\xff\xd8"
    read.assert_awaited_once_with(stream, 1, 700_000)
    to_jpeg.assert_awaited_once_with(b"ps", "/ffmpeg")


def test_ffmpeg_binary_comes_from_ha_ffmpeg_manager() -> None:
    fake = MagicMock()
    fake.get_ffmpeg_manager.return_value.binary = "/opt/ffmpeg"
    with patch.dict(sys.modules, {"homeassistant.components.ffmpeg": fake}):
        assert ffmpeg_binary(MagicMock()) == "/opt/ffmpeg"


def test_find_stream_looks_in_loaded_entries() -> None:
    hass = MagicMock()
    stream = MagicMock()
    entry = MagicMock()
    entry.runtime_data.streams = {"BK1": stream}
    hass.config_entries.async_loaded_entries.return_value = [entry]
    assert find_stream(hass, "BK1") is stream
    assert find_stream(hass, "BK9") is None
    hass.config_entries.async_loaded_entries.assert_called_with("ezviz_cloud")


class _Proc:
    """A fake ffmpeg: echoes stdin to stdout, prefixed, until stdin closes."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdin_data = bytearray()
        self._out: asyncio.Queue[bytes] = asyncio.Queue()
        self.killed = False
        proc = self

        class _Stdin:
            def write(self, data: bytes) -> None:
                proc.stdin_data += data
                proc._out.put_nowait(b"ts:" + data)

            async def drain(self) -> None:
                return None

            def close(self) -> None:
                proc._out.put_nowait(b"")

        class _Stdout:
            async def read(self, _n: int) -> bytes:
                return await proc._out.get()

        self.stdin = _Stdin()
        self.stdout = _Stdout()

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.returncode = self.returncode if self.returncode is not None else -9
        return self.returncode


def _request(hass: MagicMock, token: str) -> MagicMock:
    request = MagicMock()
    request.app = {live.KEY_HASS: hass}
    request.query = {"token": token}
    return request


async def _serve(stream: object, token: str, proc: _Proc | None = None):  # type: ignore[no-untyped-def]
    hass = MagicMock()
    written: list[bytes] = []
    response = MagicMock()
    response.prepare = AsyncMock()
    response.write = AsyncMock(side_effect=written.append)
    with (
        patch.object(live, "find_stream", return_value=stream),
        patch.object(live, "ffmpeg_binary", return_value="/ffmpeg"),
        patch.object(live.web, "StreamResponse", return_value=response),
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc or _Proc())) as spawn,
    ):
        result = await LiveStreamView().get(_request(hass, token), "BK1")
    return result, written, spawn


async def test_view_remuxes_the_stream_to_mpegts() -> None:
    async def frames() -> AsyncIterator[bytes]:
        yield b"key"
        yield b"next"

    stream = MagicMock(token="tok", frames=frames)
    proc = _Proc()
    _, written, spawn = await _serve(stream, "tok", proc)
    assert written == [b"ts:key", b"ts:next"]
    args = spawn.await_args.args
    assert args[0] == "/ffmpeg"
    assert args[args.index("-c") + 1] == "copy"
    assert args[-2:] == ("mpegts", "pipe:1")
    assert proc.killed


@pytest.mark.parametrize(("found", "token"), [(False, "tok"), (True, "wrong")])
async def test_view_hides_unknown_cameras_and_bad_tokens(found: bool, token: str) -> None:
    stream = MagicMock(token="tok") if found else None
    with pytest.raises(web.HTTPNotFound):
        await _serve(stream, token)


async def test_view_answers_503_when_the_camera_does_not_stream() -> None:
    async def frames() -> AsyncIterator[bytes]:
        raise EzvizCloudError("asleep")
        yield b""  # pragma: no cover

    with pytest.raises(web.HTTPServiceUnavailable):
        await _serve(MagicMock(token="tok", frames=frames), "tok")


async def test_view_stops_when_the_stream_fails_midway_or_the_reader_leaves() -> None:
    async def frames() -> AsyncIterator[bytes]:
        yield b"key"
        raise EzvizCloudError("dropped")

    _, written, _ = await _serve(MagicMock(token="tok", frames=frames), "tok")
    assert written == [b"ts:key"]

    async def endless() -> AsyncIterator[bytes]:
        while True:
            yield b"f"
            await asyncio.sleep(0)

    hass = MagicMock()
    response = MagicMock()
    response.prepare = AsyncMock()
    response.write = AsyncMock(side_effect=ConnectionResetError)
    proc = _Proc()
    proc.returncode = 0
    with (
        patch.object(live, "find_stream", return_value=MagicMock(token="tok", frames=endless)),
        patch.object(live, "ffmpeg_binary", return_value="/ffmpeg"),
        patch.object(live.web, "StreamResponse", return_value=response),
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
    ):
        assert await LiveStreamView().get(_request(hass, "tok"), "BK1") is response
    assert not proc.killed  # it had already exited
