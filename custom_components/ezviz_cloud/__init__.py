"""EZVIZ Cloud: live view of EZVIZ cameras through the EZVIZ Open Platform."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .api import Camera, EzvizCloudApi, EzvizCloudAuthError, EzvizCloudError
from .const import (
    CARD_FILENAME,
    CARD_URL,
    CONF_APP_KEY,
    CONF_APP_SECRET,
    CONF_MAX_PER_CAMERA,
    CONF_REGION,
    CONF_RETENTION_DAYS,
    DATA_RECORDER,
    DEFAULT_MAX_PER_CAMERA,
    DEFAULT_RETENTION_DAYS,
    DOMAIN,
    MODE_VIEW,
    REGIONS,
    signal_recorded,
)
from .recording import RecordingSessions, RecordingStore, RecordingUploadView
from .token import TokenManager
from .websocket import async_register_commands

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CAMERA, Platform.SELECT, Platform.SENSOR]


@dataclass
class EzvizCloudData:
    """What an entry keeps at runtime."""

    manager: TokenManager
    cameras: list[Camera]
    # Recording mode per serial; the select entities own and restore it.
    modes: dict[str, str]


type EzvizCloudConfigEntry = ConfigEntry[EzvizCloudData]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Serve the card, register the websocket commands and start the recorder."""
    card = Path(__file__).parent / "frontend" / CARD_FILENAME
    content = await hass.async_add_executor_job(card.read_bytes)
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card), True)])
    # The file is served with a month-long cache, so the URL carries a hash of its
    # content: any change to the card reaches browsers on the next page load.
    add_extra_js_url(hass, f"{CARD_URL}?v={hashlib.sha256(content).hexdigest()[:12]}")
    async_register_commands(hass)

    media_root = Path(hass.config.media_dirs.get("local") or hass.config.path("media"))
    store = RecordingStore(media_root)
    if recovered := await hass.async_add_executor_job(store.recover):
        _LOGGER.info("Closed %s recording(s) left open by a restart", recovered)
    sessions = RecordingSessions(hass, store)
    hass.data[DATA_RECORDER] = sessions
    hass.http.register_view(RecordingUploadView())

    async def _expire(_now: datetime) -> None:
        await sessions.expire()

    async_track_time_interval(hass, _expire, timedelta(seconds=10))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EzvizCloudConfigEntry) -> bool:
    """Validate the credentials, list the cameras and set up their entities."""
    api = EzvizCloudApi(
        async_get_clientsession(hass),
        REGIONS[entry.data[CONF_REGION]],
        entry.data[CONF_APP_KEY],
        entry.data[CONF_APP_SECRET],
    )
    manager = TokenManager(api)
    try:
        token = await manager.async_get_token()
        listed = await manager.api.async_get_cameras(token.token)
    except EzvizCloudAuthError as err:
        raise ConfigEntryError(f"EZVIZ rejected the appKey/appSecret: {err}") from err
    except EzvizCloudError as err:
        raise ConfigEntryNotReady(str(err)) from err

    # One device per serial: a multi-channel device shares a single code and folder.
    cameras: dict[str, Camera] = {}
    for camera in listed:
        cameras.setdefault(camera.serial, camera)
    entry.runtime_data = EzvizCloudData(
        manager, list(cameras.values()), dict.fromkeys(cameras, MODE_VIEW)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    store = hass.data[DATA_RECORDER].store

    async def _cleanup(serial: str) -> None:
        removed = await hass.async_add_executor_job(
            store.cleanup,
            serial,
            int(entry.options.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS)),
            int(entry.options.get(CONF_MAX_PER_CAMERA, DEFAULT_MAX_PER_CAMERA)),
            dt_util.now(),
        )
        if removed:
            _LOGGER.debug("Deleted %s old recording(s) of %s", removed, serial)

    async def _cleanup_all(_now: datetime | None = None) -> None:
        for serial in cameras:
            await _cleanup(serial)

    for serial in cameras:

        async def _on_recorded(serial: str = serial) -> None:
            await _cleanup(serial)

        entry.async_on_unload(async_dispatcher_connect(hass, signal_recorded(serial), _on_recorded))
    entry.async_on_unload(async_track_time_interval(hass, _cleanup_all, timedelta(hours=24)))
    await _cleanup_all()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EzvizCloudConfigEntry) -> bool:
    """Remove the entities; open upload sessions close on their own."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
