"""Sensor with the time of the latest recording of each camera."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EzvizCloudConfigEntry, EzvizCloudData
from .api import Camera
from .const import DATA_RECORDER, signal_recorded
from .entity import EzvizCloudEntity


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: EzvizCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One last-recording sensor per camera."""
    data = entry.runtime_data
    async_add_entities([EzvizCloudLastRecording(data, camera) for camera in data.cameras])


class EzvizCloudLastRecording(EzvizCloudEntity, SensorEntity):
    """Read from disk, so it survives restarts and reflects the cleanup."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, data: EzvizCloudData, camera: Camera) -> None:
        super().__init__(data, camera, "last_recording")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_recorded(self._serial), self._async_refresh)
        )
        await self._async_refresh()

    async def _async_refresh(self) -> None:
        store = self.hass.data[DATA_RECORDER].store
        recording = await self.hass.async_add_executor_job(store.latest, self._serial)
        if recording is None:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
        else:
            self._attr_native_value = recording.started
            self._attr_extra_state_attributes = {
                "video": store.uri(recording.video) if recording.video else None,
                "photo": store.uri(recording.photo) if recording.photo else None,
            }
        self.async_write_ha_state()
