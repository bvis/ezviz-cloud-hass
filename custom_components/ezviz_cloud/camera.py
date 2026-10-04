"""Camera showing the photo of the latest recording."""

from __future__ import annotations

from homeassistant.components.camera import Camera as CameraEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EzvizCloudConfigEntry, EzvizCloudData
from .api import Camera
from .const import DATA_RECORDER
from .entity import EzvizCloudEntity


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: EzvizCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One last-photo camera per camera."""
    data = entry.runtime_data
    async_add_entities([EzvizCloudLastPhoto(data, camera) for camera in data.cameras])


class EzvizCloudLastPhoto(EzvizCloudEntity, CameraEntity):
    """The video never reaches Home Assistant, so this only shows saved photos."""

    def __init__(self, data: EzvizCloudData, camera: Camera) -> None:
        super().__init__(data, camera, "last_photo")

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        store = self.hass.data[DATA_RECORDER].store
        for recording in await self.hass.async_add_executor_job(store.recordings, self._serial):
            if recording.photo is not None:
                return await self.hass.async_add_executor_job(recording.photo.read_bytes)
        return None
