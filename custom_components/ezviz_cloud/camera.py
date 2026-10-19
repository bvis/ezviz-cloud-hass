"""Cameras: the photo of the latest recording, and the live view.

Both show the last saved photo as their picture, so a dashboard never wakes the
camera. The live camera also streams: go2rtc and HA's stream worker read the
shared live stream through ``LiveStreamView``, only while someone watches.
"""

from __future__ import annotations

from homeassistant.components.camera import Camera as CameraEntity
from homeassistant.components.camera.const import CameraEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EzvizCloudConfigEntry, EzvizCloudData
from .api import Camera
from .const import DATA_RECORDER, DOMAIN
from .entity import EzvizCloudEntity


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
        for entity in (EzvizCloudLastPhoto(data, camera), EzvizCloudLive(data, camera))
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

    async def stream_source(self) -> str:
        # ponytail: loopback to HA's own port; behind HA's TLS, go2rtc and the stream
        # worker must accept its certificate for 127.0.0.1.
        api = self.hass.config.api
        scheme = "https" if api is not None and api.use_ssl else "http"
        port = api.port if api is not None else 8123
        token = self._data.streams[self._serial].token
        return f"{scheme}://127.0.0.1:{port}/api/{DOMAIN}/live/{self._serial}?token={token}"
