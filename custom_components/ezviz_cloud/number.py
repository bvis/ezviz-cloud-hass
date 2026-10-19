"""Clip length per camera, used by the record button."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, RestoreNumber
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EzvizCloudConfigEntry, EzvizCloudData
from .api import Camera
from .const import CLIP_MAX_SECONDS, CLIP_MIN_SECONDS, DEFAULT_CLIP_SECONDS
from .entity import EzvizCloudEntity

# Nothing is polled.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: EzvizCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One clip length per camera."""
    data = entry.runtime_data
    async_add_entities([EzvizCloudClipLength(data, camera) for camera in data.cameras])


class EzvizCloudClipLength(EzvizCloudEntity, RestoreNumber):
    """How many seconds of video a clip keeps."""

    _attr_device_class = NumberDeviceClass.DURATION
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_native_min_value = CLIP_MIN_SECONDS
    _attr_native_max_value = CLIP_MAX_SECONDS
    _attr_native_step = 1

    def __init__(self, data: EzvizCloudData, camera: Camera) -> None:
        super().__init__(data, camera, "clip_seconds")
        data.clip_seconds.setdefault(camera.serial, DEFAULT_CLIP_SECONDS)

    @property
    def native_value(self) -> int:
        return self._data.clip_seconds[self._serial]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            value = int(last.native_value)
            if CLIP_MIN_SECONDS <= value <= CLIP_MAX_SECONDS:
                self._data.clip_seconds[self._serial] = value

    async def async_set_native_value(self, value: float) -> None:
        self._data.clip_seconds[self._serial] = int(value)
        self.async_write_ha_state()
