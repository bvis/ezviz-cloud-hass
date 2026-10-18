"""Per-camera buttons that capture a photo or a short clip, server-side, on demand.

Meant for automations: wire a doorbell relay to press one and the integration
wakes the camera, reads the live stream and saves it like any other recording,
without a browser open. The last-photo camera and last-recording sensor refresh
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
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EzvizCloudConfigEntry, EzvizCloudData
from .api import Camera, EzvizCloudError
from .const import (
    CONF_CODES,
    DATA_RECORDER,
    DEFAULT_CLIP_SECONDS,
    MODE_PHOTO,
    MODE_RECORD,
    signal_recorded,
)
from .entity import EzvizCloudEntity
from .snapshot import async_capture_ps, async_ps_to_jpeg, async_ps_to_mp4, decrypt_ps

_LOGGER = logging.getLogger(__name__)

# The clear start of the stream (about 3 s) is skipped, so read that much more.
_CLEAR_START_SECONDS = 3
# Caps the read at about twice the card's 1.5 Mbps; 60 s is about 40 MB.
_CLIP_BYTES_PER_SECOND = 700_000


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
    """A photo, a clip and a capture-by-mode button per camera, sharing one stream at a time."""
    data = entry.runtime_data
    entities: list[ButtonEntity] = []
    for camera in data.cameras:
        lock = asyncio.Lock()
        photo = EzvizCloudCapture(data, camera, entry, lock)
        clip = EzvizCloudRecordClip(data, camera, entry, lock)
        entities += [photo, clip, EzvizCloudCaptureByMode(data, camera, photo, clip)]
    async_add_entities(entities)


class EzvizCloudButton(EzvizCloudEntity, ButtonEntity):
    """Opens the live stream on press, at most one stream per camera."""

    _key: str
    _what: str

    def __init__(
        self,
        data: EzvizCloudData,
        camera: Camera,
        entry: EzvizCloudConfigEntry,
        lock: asyncio.Lock,
    ) -> None:
        super().__init__(data, camera, self._key)
        self._channel = camera.channel
        self._entry = entry
        self._streaming = lock

    async def async_press(self) -> None:
        """Wake the camera, read the stream and save what it gives."""
        # A doorbell can fire twice in a row; one stream per camera is enough.
        if self._streaming.locked():
            _LOGGER.debug("Stream of %s already open, press ignored", self._serial)
            return
        async with self._streaming:
            code = self._entry.options.get(CONF_CODES, {}).get(self._serial)
            manager = self._data.manager
            try:
                token = await manager.async_get_token()
                url = await manager.api.async_live_url(
                    token.token, self._serial, self._channel, code
                )
                await self._save(url, code)
            except EzvizCloudError as err:
                raise HomeAssistantError(
                    f"Could not capture a {self._what} of {self._serial}: {err}"
                ) from err
            async_dispatcher_send(self.hass, signal_recorded(self._serial))
            _LOGGER.debug("Captured a %s of %s", self._what, self._serial)

    async def _save(self, url: str, code: str | None) -> None:
        """Read the stream at ``url`` and store what this button produces."""


class EzvizCloudCapture(EzvizCloudButton):
    """Captures a still from the live stream and stores it as the camera's last photo."""

    _key = "capture"
    _what = "photo"

    async def _save(self, url: str, code: str | None) -> None:
        ps = await async_capture_ps(async_get_clientsession(self.hass), url)
        clear, _codec = await self.hass.async_add_executor_job(decrypt_ps, ps, code)
        jpeg = await async_ps_to_jpeg(clear, _ffmpeg_binary(self.hass))
        store = self.hass.data[DATA_RECORDER].store
        path = store.photo_path(self._serial, store.stem_for(dt_util.now()))
        await self.hass.async_add_executor_job(store.save_photo, path, jpeg)


class EzvizCloudRecordClip(EzvizCloudButton):
    """Records a short clip of the live stream, plus its first frame as the photo."""

    _key = "record"
    _what = "clip"

    async def _save(self, url: str, code: str | None) -> None:
        seconds = self._data.clip_seconds.get(self._serial, DEFAULT_CLIP_SECONDS)
        seconds += _CLEAR_START_SECONDS
        ps = await async_capture_ps(
            async_get_clientsession(self.hass),
            url,
            capture_seconds=seconds,
            max_bytes=seconds * _CLIP_BYTES_PER_SECOND,
        )
        clear, codec = await self.hass.async_add_executor_job(decrypt_ps, ps, code)
        ffmpeg = _ffmpeg_binary(self.hass)
        mp4 = await async_ps_to_mp4(clear, codec, ffmpeg)
        jpeg = await async_ps_to_jpeg(clear, ffmpeg)
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
