"""Cameras: the photo of the latest recording, and the live view.

Both show the last saved photo as their picture, so a dashboard never wakes the
camera. The live camera also streams: go2rtc and HA's stream worker read the
shared live stream through ``LiveStreamView``, only while someone watches.
"""

from __future__ import annotations

from homeassistant.components.camera import Camera as CameraEntity
from homeassistant.components.camera.const import CameraEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EzvizCloudConfigEntry, EzvizCloudData
from .api import Camera
from .const import DATA_RECORDER, DOMAIN
from .entity import EzvizCloudEntity

# Nothing is polled.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: EzvizCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """A last-photo and a live camera per camera."""
    data = entry.runtime_data
    async_add_entities(
        entity
        for camera in data.cameras
        for entity in (
            EzvizCloudLastPhoto(data, camera),
            EzvizCloudLive(data, camera),
            EzvizCloudLiveOtherLens(data, camera),
        )
    )


class EzvizCloudLastPhoto(EzvizCloudEntity, CameraEntity):
    """Shows the photo of the latest recording."""

    _key = "last_photo"

    def __init__(self, data: EzvizCloudData, camera: Camera) -> None:
        super().__init__(data, camera, self._key)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        store = self.hass.data[DATA_RECORDER].store
        for recording in await self.hass.async_add_executor_job(store.recordings, self._serial):
            if recording.photo is not None:
                return await self.hass.async_add_executor_job(recording.photo.read_bytes)
        return None


class EzvizCloudLive(EzvizCloudLastPhoto):
    """The live view, as a camera any card, notification or bridge can play."""

    _key = "live"
    _attr_supported_features = CameraEntityFeature.STREAM

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._data.streams[self._serial].no_video_listeners.add(self._stop_stream_worker)

    async def async_will_remove_from_hass(self) -> None:
        self._data.streams[self._serial].no_video_listeners.discard(self._stop_stream_worker)
        await super().async_will_remove_from_hass()

    @callback
    def _stop_stream_worker(self) -> None:
        # HA's stream worker retries a source that never gave a segment until HA
        # restarts, even with nobody watching (#24): stop it. Opening the camera
        # again starts it anew.
        if self.stream is not None:
            self.hass.async_create_task(self.stream.stop())

    async def stream_source(self) -> str:
        # ponytail: loopback to HA's own port; behind HA's TLS, go2rtc and the stream
        # worker must accept its certificate for 127.0.0.1.
        api = self.hass.config.api
        scheme = "https" if api is not None and api.use_ssl else "http"
        port = api.port if api is not None else 8123
        token = self._data.streams[self._serial].token
        # `auth`, not `token`: Home Assistant's stream names its source when it fails
        # to open (routine while a battery camera sleeps) and only hides that parameter.
        return f"{scheme}://127.0.0.1:{port}/api/{DOMAIN}/live/{self._serial}?auth={token}{self._query()}"

    def _query(self) -> str:
        return ""


class EzvizCloudLiveOtherLens(EzvizCloudLive):
    """The other lens of a camera that sends two in one stream, next to the live camera.

    It reads the same shared stream, so watching both lenses wakes the camera
    once and costs no extra request. Disabled by default: a camera with one lens
    has nothing to show here.
    """

    _key = "live_other_lens"
    _attr_entity_registry_enabled_default = False

    def _query(self) -> str:
        # The track the live camera is not showing; "as sent" shows the first.
        return "&track=1" if self._data.streams[self._serial].track == 2 else "&track=2"
