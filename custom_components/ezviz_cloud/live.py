"""One live stream per camera, shared by the live camera entity and the capture buttons.

EZVIZ refuses a second stream of a camera while one is open, and a peephole that
was just streaming can refuse a new one for minutes. So every reader of a camera
(the camera entity's HTTP view, read by go2rtc and HA's stream worker, and the
photo and clip buttons) shares one live WebSocket: the first reader opens it,
and it closes ``LINGER`` seconds after the last one leaves, so a doorbell that
records a clip and sends a live notification opens it once.

The stream is decrypted pack by pack (a pack holds one frame) in the executor,
and each reader starts at a keyframe. Requests to EZVIZ per open: one
``live/url/ezopen`` request plus the live WebSocket, kept only while read.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import secrets
from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView

from .api import Camera, EzvizCloudError
from .const import DOMAIN
from .snapshot import PackSplitter, async_iter_stream, async_ps_to_jpeg, decrypt_packs
from .token import TokenManager

if TYPE_CHECKING:
    from . import EzvizCloudConfigEntry

_LOGGER = logging.getLogger(__name__)

# Keeps the stream open between a clip and a notification opened right after it.
LINGER = 20
# After an open that gave no video, refuse new opens for this long instead of
# waking the camera again for every retry.
COOLDOWN = 60


class EzvizCloudCooldownError(EzvizCloudError):
    """The camera failed to stream less than ``COOLDOWN`` seconds ago."""


# A reader this far behind (about 30 s of video) is dropped instead of buffered.
_MAX_BACKLOG = 450
# A clip reads at most this long past its length before giving up on a stalled stream.
_STALL_MARGIN = 30
# A photo reads this much from the keyframe on: the keyframe itself is enough.
_PHOTO_SECONDS = 1
_PHOTO_BYTES = 700_000

type _Item = tuple[bytes, bool] | Exception | None


class LiveStream:
    """The shared live stream of one camera."""

    def __init__(
        self,
        hass: HomeAssistant,
        manager: TokenManager,
        camera: Camera,
        code: Callable[[], str | None],
    ) -> None:
        self._hass = hass
        self._manager = manager
        self.camera = camera
        self._code = code
        self._readers: set[asyncio.Queue[_Item]] = set()
        self._task: asyncio.Task[None] | None = None
        self._linger: asyncio.TimerHandle | None = None
        self._cooldown_until = 0.0
        # Whether the current open has handed a keyframe to its readers.
        self._video = False
        # Called when an open ends without video (the live camera stops HA's stream worker).
        self.on_no_video: Callable[[], None] | None = None
        self.codec = "hevc"
        # Guards the HTTP view, which go2rtc reads without Home Assistant credentials.
        self.token = secrets.token_urlsafe(24)

    @property
    def active(self) -> bool:
        """Whether the stream is open (or opening)."""
        return self._task is not None

    async def frames(self) -> AsyncGenerator[bytes]:
        """Decrypted MPEG-PS from the next keyframe on, for as long as it is read.

        Use it with ``contextlib.aclosing`` so leaving early releases the stream.
        """
        loop = asyncio.get_running_loop()
        if loop.time() < self._cooldown_until:
            raise EzvizCloudCooldownError("The camera did not stream a moment ago; try again later")
        queue: asyncio.Queue[_Item] = asyncio.Queue()
        self._readers.add(queue)
        if self._linger is not None:
            self._linger.cancel()
            self._linger = None
        if self._task is None:
            self._task = self._hass.async_create_background_task(
                self._run(), f"{DOMAIN} live {self.camera.serial}"
            )
        started = False
        try:
            while True:
                item = await queue.get()
                if isinstance(item, Exception):
                    raise item
                if item is None:
                    return
                data, keyframe = item
                started = started or keyframe
                if started:
                    yield data
        finally:
            self._readers.discard(queue)
            if not self._readers and self._task is not None and self._linger is None:
                self._linger = loop.call_later(LINGER, self._stop)

    def _stop(self) -> None:
        self._linger = None
        if not self._readers and self._task is not None:
            if not self._video:
                # Every reader gave up waiting for a picture.
                self._no_video()
            self._task.cancel()

    def _no_video(self) -> None:
        self._cooldown_until = asyncio.get_running_loop().time() + COOLDOWN
        if self.on_no_video is not None:
            self.on_no_video()

    async def async_close(self) -> None:
        """Close the stream now (the entry is unloading)."""
        if self._linger is not None:
            self._linger.cancel()
            self._linger = None
        if (task := self._task) is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            # A task cancelled before it ran never told its readers.
            self._task = None
            for queue in self._readers:
                queue.put_nowait(None)

    async def _run(self) -> None:
        """Play the stream and hand each decrypted pack to every reader."""
        self._video = closed = False
        end: _Item = None
        try:
            code = self._code()
            token = await self._manager.async_get_token()
            url = await self._manager.api.async_live_url(
                token.token, self.camera.serial, self.camera.channel, code
            )
            # The stream opens with a group of pictures that doesn't decode; with a
            # code, decrypting it garbles it further. Readers start at the next one.
            packs = PackSplitter(skip_first_group=bool(code))
            async for data in async_iter_stream(async_get_clientsession(self._hass), url):
                if not (batch := packs.feed(data)):
                    continue
                self.codec = packs.codec
                clear = await self._hass.async_add_executor_job(
                    decrypt_packs, [p for p, _ in batch], code, packs.codec
                )
                for pack, (_, keyframe) in zip(clear, batch, strict=True):
                    self._broadcast((pack, keyframe))
                    self._video = self._video or keyframe
        except EzvizCloudError as err:
            _LOGGER.debug("Live stream of %s failed: %s", self.camera.serial, err)
            end = err
        except asyncio.CancelledError:
            closed = True  # on purpose; a linger stop without video already cooled down
            raise
        finally:
            self._task = None
            if not self._video and not closed:
                self._no_video()
                end = end or EzvizCloudError("The camera sent no video")
            for queue in self._readers:
                queue.put_nowait(end)

    def _broadcast(self, item: _Item) -> None:
        for queue in list(self._readers):
            if queue.qsize() >= _MAX_BACKLOG:
                self._readers.discard(queue)
                queue.put_nowait(EzvizCloudError("Reader fell behind the live stream"))
            else:
                queue.put_nowait(item)


async def async_read(stream: LiveStream, seconds: float, max_bytes: int) -> bytes:
    """Read ``seconds`` of the shared stream from its next keyframe, capped at ``max_bytes``."""
    loop = asyncio.get_running_loop()
    buffer = bytearray()
    end: float | None = None
    try:
        async with asyncio.timeout(seconds + _STALL_MARGIN):
            async with contextlib.aclosing(stream.frames()) as frames:
                async for data in frames:
                    buffer += data
                    end = end or loop.time() + seconds
                    if loop.time() >= end or len(buffer) >= max_bytes:
                        break
    except TimeoutError as err:
        if not buffer:
            raise EzvizCloudError("No video received; the camera may be asleep") from err
    if not buffer:
        raise EzvizCloudError("The stream ended before its first keyframe")
    return bytes(buffer)


async def async_grab_jpeg(hass: HomeAssistant, stream: LiveStream) -> bytes:
    """A still of the shared live stream: its next keyframe."""
    ps = await async_read(stream, _PHOTO_SECONDS, _PHOTO_BYTES)
    return await async_ps_to_jpeg(ps, ffmpeg_binary(hass))


def ffmpeg_binary(hass: HomeAssistant) -> str:
    """The ffmpeg binary HA is configured to use. Imported lazily to keep the
    module importable where HA's ffmpeg component (haffmpeg) is absent."""
    from homeassistant.components.ffmpeg import get_ffmpeg_manager

    return get_ffmpeg_manager(hass).binary


class LiveStreamView(HomeAssistantView):
    """Serves a camera's live stream as MPEG-TS to go2rtc and HA's stream worker.

    Neither can send Home Assistant credentials, so the stream's random token in
    the query guards it. The video is copied, not re-encoded.
    """

    url = f"/api/{DOMAIN}/live/{{serial}}"
    name = f"api:{DOMAIN}:live"
    requires_auth = False

    async def get(self, request: web.Request, serial: str) -> web.StreamResponse:
        """Stream MPEG-TS while the client stays connected."""
        hass = request.app[KEY_HASS]
        stream = find_stream(hass, serial)
        if stream is None or not hmac.compare_digest(request.query.get("token", ""), stream.token):
            raise web.HTTPNotFound
        async with contextlib.aclosing(stream.frames()) as frames:
            try:
                first = await anext(frames)
            except (EzvizCloudError, StopAsyncIteration) as err:
                raise web.HTTPServiceUnavailable from err
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_binary(hass),
                *("-hide_banner", "-loglevel", "error", "-fflags", "+genpts"),
                # The parameter sets come with the first keyframe: don't wait 5 s to probe.
                *("-analyzeduration", "1000000"),
                *("-f", "mpeg", "-i", "pipe:0", "-map", "0:v:0", "-c", "copy"),
                *("-f", "mpegts", "pipe:1"),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            assert proc.stdin is not None
            assert proc.stdout is not None
            stdin = proc.stdin

            async def _feed() -> None:
                try:
                    stdin.write(first)
                    async for data in frames:
                        stdin.write(data)
                        await stdin.drain()
                except (EzvizCloudError, ConnectionError) as err:
                    _LOGGER.debug("Live stream of %s ended: %s", serial, err)
                finally:
                    with contextlib.suppress(OSError):
                        stdin.close()

            feeder = asyncio.create_task(_feed())
            response = web.StreamResponse()
            response.content_type = "video/mp2t"
            try:
                await response.prepare(request)
                while chunk := await proc.stdout.read(65536):
                    await response.write(chunk)
            except ConnectionError:
                pass  # the reader left
            finally:
                feeder.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await feeder
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
        return response


def find_stream(hass: HomeAssistant, serial: str) -> LiveStream | None:
    """The live stream of a camera of any loaded entry."""
    entries: list[EzvizCloudConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    for entry in entries:
        if (stream := entry.runtime_data.streams.get(serial)) is not None:
            return stream
    return None
