"""A per-camera button that captures one photo, server-side, on demand.

Meant for automations: wire a doorbell relay to press it and the integration
wakes the camera, grabs a keyframe and saves it like any other photo, without a
browser open. The last-photo camera and last-recording sensor refresh on their
own through the recorded signal, and retention applies.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EzvizCloudConfigEntry, EzvizCloudData
from .api import Camera, EzvizCloudError
from .const import CONF_CODES, DATA_RECORDER, signal_recorded
from .entity import EzvizCloudEntity
from .snapshot import async_annexb_to_jpeg, async_capture_ps, decrypt_and_demux

_LOGGER = logging.getLogger(__name__)


def _ffmpeg_binary(hass: HomeAssistant) -> str:
    """The ffmpeg binary HA is configured to use. Imported lazily to keep the
    module importable where HA's ffmpeg component (haffmpeg) is absent."""
    from homeassistant.components.ffmpeg import get_ffmpeg_manager

    return get_ffmpeg_manager(hass).binary


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: EzvizCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One capture button per camera."""
    data = entry.runtime_data
    async_add_entities([EzvizCloudCapture(data, camera, entry) for camera in data.cameras])


class EzvizCloudCapture(EzvizCloudEntity, ButtonEntity):
    """Captures a still from the live stream and stores it as the camera's last photo."""

    def __init__(self, data: EzvizCloudData, camera: Camera, entry: EzvizCloudConfigEntry) -> None:
        super().__init__(data, camera, "capture")
        self._channel = camera.channel
        self._entry = entry
        self._capturing = asyncio.Lock()

    async def async_press(self) -> None:
        """Wake the camera, grab a keyframe and save it as a photo."""
        # A doorbell can fire twice in a row; one stream per camera is enough.
        if self._capturing.locked():
            _LOGGER.debug("Capture of %s already running, press ignored", self._serial)
            return
        async with self._capturing:
            await self._capture()

    async def _capture(self) -> None:
        code = self._entry.options.get(CONF_CODES, {}).get(self._serial)
        manager = self._data.manager
        try:
            token = await manager.async_get_token()
            url = await manager.api.async_live_url(token.token, self._serial, self._channel, code)
            ps = await async_capture_ps(async_get_clientsession(self.hass), url)
            annexb, codec = await self.hass.async_add_executor_job(decrypt_and_demux, ps, code)
            jpeg = await async_annexb_to_jpeg(annexb, codec, _ffmpeg_binary(self.hass))
        except EzvizCloudError as err:
            raise HomeAssistantError(f"Could not capture a photo of {self._serial}: {err}") from err

        store = self.hass.data[DATA_RECORDER].store
        stem = store.stem_for(dt_util.now())
        path = store.photo_path(self._serial, stem)
        await self.hass.async_add_executor_job(store.save_photo, path, jpeg)
        async_dispatcher_send(self.hass, signal_recorded(self._serial))
        _LOGGER.debug("Captured a photo of %s", self._serial)
