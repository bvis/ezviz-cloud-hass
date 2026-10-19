"""Per-camera buttons that capture a photo or a short clip, server-side, on demand.

Meant for automations: wire a doorbell relay to press one and the integration
wakes the camera, reads its live stream (shared with the live camera, so a
notification showing it costs no second stream) and saves it like any other
recording, without a browser open. The last-photo camera and last-recording sensor refresh
on their own through the recorded signal, and retention applies. The
capture-by-mode button picks one of the two from the camera's mode, so an
automation can wire a doorbell once and switch the mode when nobody is home.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EzvizCloudConfigEntry, EzvizCloudData
from .api import Camera, EzvizCloudError
from .const import (
    DATA_RECORDER,
    DEFAULT_CLIP_SECONDS,
    MODE_PHOTO,
    MODE_RECORD,
    signal_recorded,
)
from .entity import EzvizCloudEntity
from .live import LiveStream, async_grab_jpeg, async_read, ffmpeg_binary
from .snapshot import async_ps_to_jpeg, async_ps_to_mp4

_LOGGER = logging.getLogger(__name__)

# Caps the read at about twice the card's 1.5 Mbps; 60 s is about 40 MB.
_CLIP_BYTES_PER_SECOND = 700_000


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: EzvizCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """A photo, a clip and a capture-by-mode button per camera, sharing one stream at a time."""
    data = entry.runtime_data
    entities: list[ButtonEntity] = []
    for camera in data.cameras:
        lock = asyncio.Lock()
        photo = EzvizCloudCapture(data, camera, lock)
        clip = EzvizCloudRecordClip(data, camera, lock)
        entities += [photo, clip, EzvizCloudCaptureByMode(data, camera, photo, clip)]
    async_add_entities(entities)


class EzvizCloudButton(EzvizCloudEntity, ButtonEntity):
    """Reads the live stream on press, one capture per camera at a time."""

    _key: str
    _what: str

    def __init__(self, data: EzvizCloudData, camera: Camera, lock: asyncio.Lock) -> None:
        super().__init__(data, camera, self._key)
        self._streaming = lock

    async def async_press(self) -> None:
        """Read the camera's shared live stream and save what it gives."""
        # A doorbell can fire twice in a row; one capture per camera is enough.
        if self._streaming.locked():
            _LOGGER.debug("Capture of %s already running, press ignored", self._serial)
            return
        async with self._streaming:
            try:
                await self._save(self._data.streams[self._serial])
            except EzvizCloudError as err:
                raise HomeAssistantError(
                    f"Could not capture a {self._what} of {self._serial}: {err}"
                ) from err
            async_dispatcher_send(self.hass, signal_recorded(self._serial))
            _LOGGER.debug("Captured a %s of %s", self._what, self._serial)

    async def _save(self, stream: LiveStream) -> None:
        """Read ``stream`` and store what this button produces."""


class EzvizCloudCapture(EzvizCloudButton):
    """Captures a still from the live stream and stores it as the camera's last photo."""

    _key = "capture"
    _what = "photo"

    async def _save(self, stream: LiveStream) -> None:
        jpeg = await async_grab_jpeg(self.hass, stream)
        store = self.hass.data[DATA_RECORDER].store
        path = store.photo_path(self._serial, store.stem_for(dt_util.now()))
        await self.hass.async_add_executor_job(store.save_photo, path, jpeg)


class EzvizCloudRecordClip(EzvizCloudButton):
    """Records a short clip of the live stream, plus its first frame as the photo."""

    _key = "record"
    _what = "clip"

    async def _save(self, stream: LiveStream) -> None:
        seconds = self._data.clip_seconds.get(self._serial, DEFAULT_CLIP_SECONDS)
        ps = await async_read(stream, seconds, seconds * _CLIP_BYTES_PER_SECOND)
        ffmpeg = ffmpeg_binary(self.hass)
        mp4 = await async_ps_to_mp4(ps, stream.codec, ffmpeg)
        jpeg = await async_ps_to_jpeg(ps, ffmpeg)
        store = self.hass.data[DATA_RECORDER].store
        stem = store.stem_for(dt_util.now())
        part = store.video_part(self._serial, stem, "mp4")
        await self.hass.async_add_executor_job(store.append, part, mp4)
        await self.hass.async_add_executor_job(store.finalize, part)
        await self.hass.async_add_executor_job(
            store.save_photo, store.photo_path(self._serial, stem), jpeg
        )


class EzvizCloudCaptureByMode(EzvizCloudEntity, ButtonEntity):
    """Presses the photo or the clip button as the camera's mode says; nothing in view mode."""

    def __init__(
        self,
        data: EzvizCloudData,
        camera: Camera,
        photo: EzvizCloudCapture,
        clip: EzvizCloudRecordClip,
    ) -> None:
        super().__init__(data, camera, "capture_by_mode")
        self._buttons = {MODE_PHOTO: photo, MODE_RECORD: clip}
        # What the last press saved, so an automation knows whether a new photo exists.
        self._attr_extra_state_attributes = {"last_capture": None}

    async def async_press(self) -> None:
        button = self._buttons.get(self._data.modes[self._serial])
        self._attr_extra_state_attributes = {"last_capture": button._what if button else "none"}
        self.async_write_ha_state()
        if button is None:
            _LOGGER.debug("%s is in view mode, nothing captured", self._serial)
            return
        await button.async_press()
