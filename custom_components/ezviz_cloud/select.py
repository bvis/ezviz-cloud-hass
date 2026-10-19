"""Recording mode per camera: view only, photo on demand, or record."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import EzvizCloudConfigEntry, EzvizCloudData
from .api import Camera
from .const import MODE_PHOTO, MODE_RECORD, MODE_VIEW
from .entity import EzvizCloudEntity

# Nothing is polled.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: EzvizCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One mode select per camera."""
    data = entry.runtime_data
    async_add_entities([EzvizCloudMode(data, camera) for camera in data.cameras])


class EzvizCloudMode(EzvizCloudEntity, SelectEntity, RestoreEntity):
    """Decides whether the card records the live view, and what the
    capture-by-mode button saves: nothing, a photo or a clip."""

    _attr_options = [MODE_VIEW, MODE_PHOTO, MODE_RECORD]

    def __init__(self, data: EzvizCloudData, camera: Camera) -> None:
        super().__init__(data, camera, "mode")

    @property
    def current_option(self) -> str:
        return self._data.modes[self._serial]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self.options:
            self._data.modes[self._serial] = last.state

    async def async_select_option(self, option: str) -> None:
        self._data.modes[self._serial] = option
        self.async_write_ha_state()
