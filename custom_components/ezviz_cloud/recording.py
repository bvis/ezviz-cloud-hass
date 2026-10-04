"""Recordings: files on disk, upload sessions from the card, and the upload view."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView
from homeassistant.util import dt as dt_util

from .const import (
    DATA_RECORDER,
    DOMAIN,
    MAX_CHUNK_BYTES,
    MAX_SESSION_BYTES,
    SESSION_IDLE_TIMEOUT,
    signal_recorded,
)

_LOGGER = logging.getLogger(__name__)

_STEM_FORMAT = "%Y-%m-%d_%H-%M-%S"
_SERIAL = re.compile(r"[A-Za-z0-9]+")
_VIDEO_SUFFIXES = (".mp4", ".webm")


@dataclass(frozen=True)
class Recording:
    """One recording: a video, a photo, or both, sharing the start time."""

    stem: str
    started: datetime
    video: Path | None
    photo: Path | None


class RecordingStore:
    """Files under <media>/ezviz_cloud/<serial>/. Blocking: call from the executor."""

    def __init__(self, media_root: Path) -> None:
        self.media_root = media_root
        self.root = media_root / DOMAIN

    def stem_for(self, when: datetime) -> str:
        """File name stem for a recording started at `when` (local time)."""
        return dt_util.as_local(when).strftime(_STEM_FORMAT)

    def _dir(self, serial: str, create: bool = False) -> Path:
        # Serials come from the camera list, but they end up in a path: be strict.
        if not _SERIAL.fullmatch(serial):
            raise ValueError(f"Unsafe serial: {serial!r}")
        folder = self.root / serial
        if create:
            folder.mkdir(parents=True, exist_ok=True)
        return folder

    def video_part(self, serial: str, stem: str, ext: str) -> Path:
        """Path the video is written to while it is being recorded."""
        return self._dir(serial, create=True) / f"{stem}.{ext}.part"

    def photo_path(self, serial: str, stem: str) -> Path:
        """Path of the photo of a recording."""
        return self._dir(serial, create=True) / f"{stem}.jpg"

    def append(self, path: Path, data: bytes) -> None:
        """Append one chunk to a video being recorded."""
        with path.open("ab") as file:
            file.write(data)

    def finalize(self, part: Path) -> Path | None:
        """Turn a finished .part into the final video; drop it if nothing arrived."""
        if not part.exists():
            return None
        if part.stat().st_size == 0:
            part.unlink()
            return None
        final = part.with_suffix("")
        part.rename(final)
        return final

    def save_photo(self, path: Path, data: bytes) -> None:
        """Write the photo atomically so the camera entity never reads half a file."""
        tmp = path.with_suffix(".jpg.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def recordings(self, serial: str) -> list[Recording]:
        """Finished recordings of a camera, newest first."""
        folder = self._dir(serial)
        if not folder.is_dir():
            return []
        videos: dict[str, Path] = {}
        photos: dict[str, Path] = {}
        for path in folder.iterdir():
            stem = path.name.split(".", 1)[0]
            if path.suffix in _VIDEO_SUFFIXES:
                videos[stem] = path
            elif path.suffix == ".jpg":
                photos[stem] = path
        found = []
        for stem in videos.keys() | photos.keys():
            try:
                started = datetime.strptime(stem, _STEM_FORMAT).replace(
                    tzinfo=dt_util.get_default_time_zone()
                )
            except ValueError:
                continue
            found.append(Recording(stem, started, videos.get(stem), photos.get(stem)))
        return sorted(found, key=lambda r: r.started, reverse=True)

    def latest(self, serial: str) -> Recording | None:
        """The newest recording of a camera."""
        recordings = self.recordings(serial)
        return recordings[0] if recordings else None

    def recover(self) -> int:
        """Close videos left half-written by a restart. Fragmented MP4/WebM play up to the cut."""
        if not self.root.is_dir():
            return 0
        return sum(1 for part in self.root.glob("*/*.part") if self.finalize(part))

    def cleanup(self, serial: str, retention_days: int, max_count: int, now: datetime) -> int:
        """Delete recordings older than the retention or beyond the count (0 = no count limit)."""
        cutoff = now - timedelta(days=retention_days)
        removed = 0
        for index, recording in enumerate(self.recordings(serial)):
            if recording.started >= cutoff and (not max_count or index < max_count):
                continue
            for path in (recording.video, recording.photo):
                if path is not None:
                    path.unlink(missing_ok=True)
            removed += 1
        return removed

    def uri(self, path: Path) -> str:
        """media-source URI of a file, for the sensor attributes."""
        return f"media-source://media_source/local/{path.relative_to(self.media_root).as_posix()}"


_EXTENSIONS = {"video/mp4": "mp4", "video/webm": "webm"}


class SessionNotFoundError(Exception):
    """No open upload session with that id."""


class SessionTooLargeError(Exception):
    """The session reached MAX_SESSION_BYTES and was closed."""


class UnsupportedTypeError(Exception):
    """The chunk is not MP4 or WebM video."""


@dataclass
class _Session:
    serial: str
    stem: str
    last_chunk: float
    part: Path | None = None
    size: int = field(default=0)


class RecordingSessions:
    """Upload sessions opened by the card, at most one per camera."""

    def __init__(
        self,
        hass: HomeAssistant,
        store: RecordingStore,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._hass = hass
        self.store = store
        self._clock = clock
        self._sessions: dict[str, _Session] = {}

    def start(self, serial: str) -> str | None:
        """Open a session, or None if this camera is already being recorded."""
        if any(s.serial == serial for s in self._sessions.values()):
            return None
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = _Session(
            serial, self.store.stem_for(dt_util.now()), self._clock()
        )
        return session_id

    def _get(self, session_id: str) -> _Session:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise SessionNotFoundError(session_id) from None

    def target(self, session_id: str) -> tuple[str, str]:
        """Serial and file stem of a session."""
        session = self._get(session_id)
        return session.serial, session.stem

    async def append(self, session_id: str, data: bytes, content_type: str) -> None:
        """Add a chunk of video to the session's file."""
        session = self._get(session_id)
        ext = _EXTENSIONS.get(content_type.split(";")[0].strip().lower())
        if ext is None:
            raise UnsupportedTypeError(content_type)
        if session.size + len(data) > MAX_SESSION_BYTES:
            await self.stop(session_id)
            raise SessionTooLargeError(session_id)
        if session.part is None:
            session.part = self.store.video_part(session.serial, session.stem, ext)
        await self._hass.async_add_executor_job(self.store.append, session.part, data)
        session.size += len(data)
        session.last_chunk = self._clock()

    async def save_photo(self, serial: str, stem: str, data: bytes) -> None:
        """Store the photo of a recording and tell the entities."""
        path = self.store.photo_path(serial, stem)
        await self._hass.async_add_executor_job(self.store.save_photo, path, data)
        async_dispatcher_send(self._hass, signal_recorded(serial))

    async def stop(self, session_id: str) -> None:
        """Close a session and keep what was recorded."""
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        if session.part is not None:
            await self._hass.async_add_executor_job(self.store.finalize, session.part)
        async_dispatcher_send(self._hass, signal_recorded(session.serial))

    async def expire(self) -> None:
        """Close sessions whose card stopped sending, e.g. a closed tab."""
        now = self._clock()
        for session_id, session in list(self._sessions.items()):
            if now - session.last_chunk > SESSION_IDLE_TIMEOUT:
                await self.stop(session_id)


class RecordingUploadView(HomeAssistantView):
    """Receives the card's video chunks for an open session."""

    url = "/api/ezviz_cloud/recording/{session_id}"
    name = "api:ezviz_cloud:recording"
    requires_auth = True

    async def post(self, request: web.Request, session_id: str) -> web.Response:
        """Append one chunk to the session's video."""
        if (request.content_length or 0) > MAX_CHUNK_BYTES:
            return self.json_message("Chunk too large", 413)
        sessions = request.app[KEY_HASS].data[DATA_RECORDER]
        data = await request.read()
        try:
            await sessions.append(session_id, data, request.content_type)
        except SessionNotFoundError:
            return self.json_message("Unknown session", 404)
        except SessionTooLargeError:
            return self.json_message("Recording too large", 413)
        except UnsupportedTypeError:
            return self.json_message("Unsupported video type", 415)
        except OSError as err:
            _LOGGER.error("Cannot write the recording: %s", err)
            return self.json_message("Cannot write the recording", 500)
        return self.json_message("ok")
