"""Base entity: one device per camera of the account."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .api import Camera
from .const import DOMAIN

if TYPE_CHECKING:
    from . import EzvizCloudData


class EzvizCloudEntity(Entity):
    """Ties an entity to its camera's device."""

    _attr_has_entity_name = True

    def __init__(self, data: EzvizCloudData, camera: Camera, key: str) -> None:
        super().__init__()
        self._data = data
        self._serial = camera.serial
        self._attr_translation_key = key
        self._attr_unique_id = f"{camera.serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, camera.serial)},
            name=camera.name,
            manufacturer="EZVIZ",
            serial_number=camera.serial,
        )
