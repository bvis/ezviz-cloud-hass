"""Where cameras and their live video come from: an Open Platform app or the EZVIZ app account.

Both hand back the same thing, the camera's raw MPEG-PS (video still encrypted
with the verification code when image encryption is on), so ``live.py`` decrypts
and shares it the same way whatever the source.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncGenerator
from typing import Any, Protocol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import Camera, EzvizCloudError
from .snapshot import async_iter_stream
from .token import TokenManager

_LOGGER = logging.getLogger(__name__)

# The official integration's domain and the type of its account entries.
EZVIZ_DOMAIN = "ezviz"
EZVIZ_CLOUD_ACCOUNT = "EZVIZ_CLOUD_ACCOUNT"

# A sleeping camera takes a few seconds to wake; after that the stream never pauses this long.
_WAKE_TIMEOUT = 20.0


class _EzvizCoordinator(Protocol):
    """What the official integration keeps at runtime: its client and camera list."""

    data: dict[str, dict[str, Any]] | None
    ezviz_client: Any


class Account(Protocol):
    """A source of cameras and live video."""

    async def async_cameras(self) -> list[Camera]:
        """Every camera of the account."""
        ...

    def async_stream(self, camera: Camera, code: str | None) -> AsyncGenerator[bytes]:
        """The camera's live MPEG-PS as it arrives; closing it closes the stream."""
        ...


class OpenPlatformAccount:
    """An EZVIZ Open Platform app: token, camera list and ezopen live stream.

    Requests to EZVIZ per stream: one ``live/url/ezopen`` plus the live WebSocket.
    """

    def __init__(self, hass: HomeAssistant, manager: TokenManager) -> None:
        self._hass = hass
        self.manager = manager

    async def async_cameras(self) -> list[Camera]:
        token = await self.manager.async_get_token()
        return await self.manager.api.async_get_cameras(token.token)

    async def async_stream(self, camera: Camera, code: str | None) -> AsyncGenerator[bytes]:
        token = await self.manager.async_get_token()
        url = await self.manager.api.async_live_url(
            token.token, camera.serial, camera.channel, code
        )
        async for data in async_iter_stream(async_get_clientsession(self._hass), url):
            yield data


class AppAccount:
    """The EZVIZ app account the official EZVIZ integration is logged in with.

    Its login is reused as is: that integration keeps the session alive, and its
    camera list costs no request. Requests to EZVIZ per stream: the stream
    resources, a stream token and the stream server, then one TCP stream.
    """

    def __init__(self, hass: HomeAssistant, unique_id: str) -> None:
        self._hass = hass
        # The official entry's unique id (the account's user name) survives re-adding it.
        self.unique_id = unique_id

    def _coordinator(self) -> _EzvizCoordinator:
        entry = self._hass.config_entries.async_entry_for_domain_unique_id(
            EZVIZ_DOMAIN, self.unique_id
        )
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            raise EzvizCloudError("The EZVIZ integration's account is not loaded")
        coordinator: _EzvizCoordinator = entry.runtime_data
        return coordinator

    async def async_cameras(self) -> list[Camera]:
        data = self._coordinator().data or {}
        return [
            Camera(
                serial=serial,
                channel=1,
                name=info.get("name") or serial,
                encrypted=bool(info.get("encrypted")),
            )
            for serial, info in data.items()
        ]

    async def async_stream(self, camera: Camera, code: str | None) -> AsyncGenerator[bytes]:
        """Read the stream in a worker thread (the library's client blocks) and hand
        its bytes over as they arrive."""
        client = self._coordinator().ezviz_client
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | Exception | None] = asyncio.Queue()
        stop = threading.Event()
        holder: list[Any] = []

        def _read() -> None:
            from pyezvizapi import open_cloud_stream  # type: ignore[attr-defined]

            end: Exception | None = None
            try:
                stream = open_cloud_stream(client, camera.serial, timeout=_WAKE_TIMEOUT)
                holder.append(stream)
                with stream:
                    stream.start()
                    for body in stream.iter_payloads():
                        if stop.is_set():
                            break
                        if body:
                            loop.call_soon_threadsafe(queue.put_nowait, body)
            # The library raises plain socket and HTTP errors as well as its own.
            except Exception as err:
                if not stop.is_set():
                    end = EzvizCloudError(f"Live stream failed: {err}")
            with contextlib.suppress(RuntimeError):  # the loop is gone (HA stopping)
                loop.call_soon_threadsafe(queue.put_nowait, end)

        # Its own thread: a stream can last minutes, too long to hold an executor worker.
        threading.Thread(target=_read, name=f"ezviz_cloud {camera.serial}", daemon=True).start()
        started = False
        try:
            while (item := await queue.get()) is not None:
                if isinstance(item, Exception):
                    raise item
                started = True
                yield item
        finally:
            stop.set()
            # Unblocks the thread's socket read right away.
            for stream in holder:
                with contextlib.suppress(Exception):
                    stream.close()
        if not started:
            raise EzvizCloudError("No video received; the camera may be asleep")
