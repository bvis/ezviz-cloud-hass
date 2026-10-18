"""Media source: recordings grouped by camera, newest first, under "EZVIZ Cloud"."""

from __future__ import annotations

from homeassistant.components.media_player.const import MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .const import DATA_RECORDER, DOMAIN
from .recording import Recording, RecordingStore

_MIME = {".mp4": "video/mp4", ".webm": "video/webm", ".jpg": "image/jpeg"}


async def async_get_media_source(hass: HomeAssistant) -> EzvizCloudMediaSource:
    """Set up the EZVIZ Cloud media source."""
    return EzvizCloudMediaSource(hass)


class EzvizCloudMediaSource(MediaSource):
    """Browse the files RecordingStore keeps; they are served by the local media view."""

    name = "EZVIZ Cloud"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    @property
    def _store(self) -> RecordingStore:
        return self.hass.data[DATA_RECORDER].store

    def _url(self, serial: str, name: str) -> str:
        return f"/media/local/{DOMAIN}/{serial}/{name}"

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Identifier is <serial>/<file name>."""
        serial, _, name = (item.identifier or "").partition("/")
        mime = _MIME.get(name[name.rfind(".") :]) if "." in name else None

        def _exists() -> bool:
            # Only names the browse tree hands out: nothing else under the folder resolves.
            try:
                recordings = self._store.recordings(serial)
            except ValueError:
                return False
            return any(
                name in (r.video and r.video.name, r.photo and r.photo.name) for r in recordings
            )

        if mime is None or not await self.hass.async_add_executor_job(_exists):
            raise Unresolvable(f"Unknown recording: {item.identifier}")
        return PlayMedia(self._url(serial, name), mime)

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Root lists cameras with recordings; a camera lists its recordings."""
        names = {
            camera.serial: camera.name
            for entry in self.hass.config_entries.async_loaded_entries(DOMAIN)
            for camera in entry.runtime_data.cameras
        }
        if not item.identifier:
            return await self.hass.async_add_executor_job(self._browse_root, names)
        try:
            recordings = await self.hass.async_add_executor_job(
                self._store.recordings, item.identifier
            )
        except ValueError:
            raise Unresolvable(f"Unknown camera: {item.identifier}") from None
        return _folder(
            item.identifier,
            names.get(item.identifier, item.identifier),
            [self._child(item.identifier, r) for r in recordings],
        )

    def _browse_root(self, names: dict[str, str]) -> BrowseMediaSource:
        root = self._store.root
        serials = [p.name for p in root.iterdir() if p.is_dir()] if root.is_dir() else []
        # A camera no longer in the account keeps its folder, shown by serial.
        cameras = [_folder(s, names.get(s, s), None) for s in serials]
        return _folder(None, self.name, sorted(cameras, key=lambda c: c.title.lower()))

    def _child(self, serial: str, recording: Recording) -> BrowseMediaSource:
        # A clip opens as its video, with its photo as the thumbnail; a photo opens as itself.
        file = recording.video or recording.photo
        assert file is not None  # RecordingStore only lists stems with a file
        is_video = recording.video is not None
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{serial}/{file.name}",
            media_class=MediaClass.VIDEO if is_video else MediaClass.IMAGE,
            media_content_type=MediaType.VIDEO if is_video else MediaType.IMAGE,
            title=recording.started.strftime("%Y-%m-%d %H:%M:%S"),
            can_play=True,
            can_expand=False,
            thumbnail=self._url(serial, recording.photo.name) if recording.photo else None,
        )


def _folder(
    identifier: str | None, title: str, children: list[BrowseMediaSource] | None
) -> BrowseMediaSource:
    return BrowseMediaSource(
        domain=DOMAIN,
        identifier=identifier,
        media_class=MediaClass.DIRECTORY,
        media_content_type="",
        title=title,
        can_play=False,
        can_expand=True,
        children=children,
        children_media_class=MediaClass.DIRECTORY if identifier is None else None,
    )
