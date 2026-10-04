"""Select entities of EZVIZ Cloud (filled in by the recording feature)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EzvizCloudConfigEntry


async def async_setup_entry(
    _hass: HomeAssistant,
    _entry: EzvizCloudConfigEntry,
    _async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Placeholder until Task 6 adds the entities."""
