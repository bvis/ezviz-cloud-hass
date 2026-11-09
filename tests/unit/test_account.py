"""Where cameras and video come from: the Open Platform app or the EZVIZ app account."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.ezviz_cloud import account
from custom_components.ezviz_cloud.account import AppAccount, OpenPlatformAccount
from custom_components.ezviz_cloud.api import Camera, EzvizCloudError

CAM = Camera("BK1", 1, "Door", True)


async def test_open_platform_lists_and_streams() -> None:
    manager = MagicMock()
    manager.async_get_token = AsyncMock(return_value=MagicMock(token="at.x"))
    manager.api.async_get_cameras = AsyncMock(return_value=[CAM])
    manager.api.async_live_url = AsyncMock(return_value="wss://x/live?a=1")
    source = OpenPlatformAccount(MagicMock(), manager)
    assert await source.async_cameras() == [CAM]
    manager.api.async_get_cameras.assert_awaited_once_with("at.x")

    async def fake_stream(_session: object, url: str):  # type: ignore[no-untyped-def]
        assert url == "wss://x/live?a=1"
        yield b"ps"

    with (
        patch.object(account, "async_iter_stream", fake_stream),
        patch.object(account, "async_get_clientsession"),
    ):
        assert [d async for d in source.async_stream(CAM, "CODE")] == [b"ps"]
    manager.api.async_live_url.assert_awaited_once_with("at.x", "BK1", 1, "CODE")


def _app(
    state: ConfigEntryState = ConfigEntryState.LOADED, data: dict | None = None
) -> tuple[AppAccount, MagicMock]:
    hass = MagicMock()
    entry = MagicMock(state=state)
    entry.runtime_data.data = data
    hass.config_entries.async_entry_for_domain_unique_id.return_value = entry
    return AppAccount(hass, "me@x"), entry


async def test_app_account_lists_the_official_integrations_cameras() -> None:
    source, _ = _app(
        data={"BK1": {"name": "Door", "encrypted": True}, "BK2": {"name": None}},
    )
    assert await source.async_cameras() == [
        CAM,
        Camera("BK2", 1, "BK2", False),
    ]
    source._hass.config_entries.async_entry_for_domain_unique_id.assert_called_with("ezviz", "me@x")
    assert await _app(data=None)[0].async_cameras() == []


async def test_app_account_needs_the_official_integration_loaded() -> None:
    source, _ = _app(ConfigEntryState.SETUP_RETRY)
    with pytest.raises(EzvizCloudError, match="not loaded"):
        await source.async_cameras()
    source._hass.config_entries.async_entry_for_domain_unique_id.return_value = None
    with pytest.raises(EzvizCloudError, match="not loaded"):
        await source.async_cameras()


class _FakeVtm:
    """Stands in for the library's stream client, read from the worker thread."""

    def __init__(self, payloads: list[bytes], error: Exception | None = None) -> None:
        self.payloads = payloads
        self.error = error
        self.closed = threading.Event()
        self.started = False

    def __enter__(self) -> _FakeVtm:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed.set()

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed.set()

    def iter_payloads(self) -> Iterator[bytes]:
        yield from self.payloads
        if self.error is not None:
            raise self.error


@contextlib.contextmanager
def _vtm(fake: _FakeVtm) -> Iterator[MagicMock]:
    opener = MagicMock(return_value=fake)
    with patch("pyezvizapi.open_cloud_stream", opener, create=True):
        yield opener


async def test_app_account_streams_what_the_camera_sends() -> None:
    source, entry = _app()
    fake = _FakeVtm([b"a", b"", b"b"])
    with _vtm(fake) as opener:
        assert [d async for d in source.async_stream(CAM, "CODE")] == [b"a", b"b"]
    opener.assert_called_once_with(entry.runtime_data.ezviz_client, "BK1", timeout=20.0)
    assert fake.started
    assert fake.closed.wait(1)


@pytest.mark.parametrize(
    ("fake", "message"),
    [
        (_FakeVtm([b"a"], OSError("reset")), "Live stream failed: reset"),
        (_FakeVtm([]), "No video received"),
    ],
)
async def test_app_account_stream_errors(fake: _FakeVtm, message: str) -> None:
    source, _ = _app()
    got: list[bytes] = []
    with _vtm(fake), pytest.raises(EzvizCloudError, match=message):
        async for data in source.async_stream(CAM, None):
            got.append(data)
    assert got == fake.payloads


async def test_app_account_closing_the_stream_stops_the_reader() -> None:
    source, _ = _app()
    release = threading.Event()

    class _Endless(_FakeVtm):
        def iter_payloads(self) -> Iterator[bytes]:
            yield b"a"
            # Blocks like a socket read until the stream is closed from the loop.
            self.closed.wait(5)
            release.set()
            yield b"late"  # arrived as the close landed: dropped

    fake = _Endless([])
    with _vtm(fake):
        stream = source.async_stream(CAM, None)
        assert await anext(stream) == b"a"
        await stream.aclose()
    # The reader wakes up and ends quietly: closing was on purpose.
    assert release.wait(1)
