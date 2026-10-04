"""Recordings: files on disk, upload sessions from the card, and the upload view."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from homeassistant.util import dt as dt_util

from .const import DOMAIN

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
