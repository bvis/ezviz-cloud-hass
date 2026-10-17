"""Server-side capture: WebSocket play, skipping the clear start, decrypt, ffmpeg."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.ezviz_cloud.api import EzvizCloudError
from custom_components.ezviz_cloud.snapshot import (
    _decrypt,
    _scan,
    async_capture_ps,
    async_ps_to_jpeg,
    async_ps_to_mp4,
    decrypt_ps,
)

IMKH = b"IMKH" + b"\x00" * 36
# 14-byte pack header; the last byte's low 3 bits say "no stuffing follows".
PACK = b"\x00\x00\x01\xba" + b"\x44\x00\x37\xc6\x84\x01\x00\xf5\xc7\xf8"


def _pes(payload: bytes) -> bytes:
    """A minimal video PES packet (stream id 0xE0) with a zero-length header."""
    body = b"\x80\x00\x00" + payload
    return b"\x00\x00\x01\xe0" + len(body).to_bytes(2, "big") + body


def _psm(stream_type: int = 0x24, other: bytes = b"") -> bytes:
    """A program stream map listing ``other`` entries, then the video stream (0xE0)."""
    entries = other + bytes([stream_type, 0xE0]) + b"\x00\x00"
    body = b"\x80\x01\x00\x00" + len(entries).to_bytes(2, "big") + entries
    return b"\x00\x00\x01\xbc" + len(body).to_bytes(2, "big") + body


def _gop(frame: bytes, stream_type: int = 0x24) -> bytes:
    """One group of pictures: a pack with the stream map, then a video packet."""
    return PACK + _psm(stream_type) + _pes(frame)


def test_scan_finds_the_second_group_and_the_codec() -> None:
    first = _gop(b"clear")
    assert _scan(first + _gop(b"live")) == (len(first), "hevc")


@pytest.mark.parametrize(("stream_type", "codec"), [(0x1B, "h264"), (0x24, "hevc"), (0x99, "hevc")])
def test_scan_reads_the_codec_from_the_stream_map(stream_type: int, codec: str) -> None:
    audio = b"\x0f\xc0\x00\x02ab"  # an audio entry with 2 bytes of descriptors, listed first
    ps = PACK + _psm(stream_type, audio) + _pes(b"v")
    assert _scan(ps) == (None, codec)


def test_scan_keeps_the_default_when_the_stream_map_lists_no_video() -> None:
    entries = b"\x0f\xc0\x00\x00"  # audio only
    body = b"\x80\x01\x00\x00" + len(entries).to_bytes(2, "big") + entries
    psm = b"\x00\x00\x01\xbc" + len(body).to_bytes(2, "big") + body
    assert _scan(PACK + psm)[1] == "hevc"


def test_scan_stops_at_a_truncated_pack_header_or_garbage() -> None:
    assert _scan(_gop(b"v") + b"\x00\x00\x01\xba\x44\x00") == (None, "hevc")
    assert _scan(_gop(b"v") + b"junk" + _gop(b"w")) == (None, "hevc")


def test_scan_ignores_start_codes_inside_payloads() -> None:
    fake_map = b"\x00\x00\x01\xbc\x00\x00"
    assert _scan(_gop(fake_map) + _pes(b"v")) == (None, "hevc")


def test_decrypt_ps_skips_the_clear_group_and_decrypts_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        "custom_components.ezviz_cloud.snapshot._decrypt",
        lambda ps, code: calls.append((ps, code)) or b"decrypted",
    )
    live = _gop(b"live", 0x1B)
    assert decrypt_ps(IMKH + _gop(b"clear", 0x1B) + live, "SECRET") == (b"decrypted", "h264")
    assert calls == [(live, "SECRET")]


def test_decrypt_ps_without_code_keeps_everything() -> None:
    ps = _gop(b"a") + _gop(b"b")
    assert decrypt_ps(IMKH + ps, None) == (ps, "hevc")


def test_decrypt_ps_needs_a_live_group() -> None:
    with pytest.raises(EzvizCloudError, match="first live keyframe"):
        decrypt_ps(IMKH + _gop(b"clear"), "SECRET")


def _ffmpeg(monkeypatch: pytest.MonkeyPatch, **communicate: object) -> dict:
    proc = MagicMock()
    proc.communicate = AsyncMock(**communicate)
    proc.wait = AsyncMock()
    created: dict = {"proc": proc}

    async def fake_exec(*args, **_kwargs):  # type: ignore[no-untyped-def]
        created["args"] = args
        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    return created


async def test_ps_to_jpeg_runs_ffmpeg_on_the_program_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _ffmpeg(monkeypatch, return_value=(b"\xff\xd8the-jpeg", b""))
    assert await async_ps_to_jpeg(b"ps", "/usr/bin/ffmpeg") == b"\xff\xd8the-jpeg"
    args = created["args"]
    assert args[0] == "/usr/bin/ffmpeg"
    assert args[args.index("-f") + 1] == "mpeg"
    assert created["proc"].communicate.await_args.args == (b"ps",)


async def test_ps_to_jpeg_raises_when_ffmpeg_decodes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ffmpeg(monkeypatch, return_value=(b"", b"Invalid data found"))
    with pytest.raises(EzvizCloudError, match="Invalid data found"):
        await async_ps_to_jpeg(b"bad", "/usr/bin/ffmpeg")


@pytest.mark.parametrize(("codec", "tagged"), [("hevc", True), ("h264", False)])
async def test_ps_to_mp4_copies_the_video(
    monkeypatch: pytest.MonkeyPatch, codec: str, tagged: bool
) -> None:
    created = _ffmpeg(monkeypatch, return_value=(b"mp4", b""))
    assert await async_ps_to_mp4(b"ps", codec, "/usr/bin/ffmpeg") == b"mp4"
    args = created["args"]
    assert args[args.index("-c") + 1] == "copy"
    assert ("hvc1" in args) is tagged


async def test_ps_to_mp4_raises_when_ffmpeg_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ffmpeg(monkeypatch, return_value=(b"", b""))
    with pytest.raises(EzvizCloudError, match="no video"):
        await async_ps_to_mp4(b"bad", "hevc", "/usr/bin/ffmpeg")


async def test_ffmpeg_is_killed_when_it_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    created = _ffmpeg(monkeypatch, side_effect=TimeoutError)
    with pytest.raises(EzvizCloudError, match="in time"):
        await async_ps_to_jpeg(b"ps", "/usr/bin/ffmpeg")
    created["proc"].kill.assert_called_once()


def _msg(kind: aiohttp.WSMsgType, data: object) -> aiohttp.WSMessage:
    return aiohttp.WSMessage(kind, data, None)


class _FakeWS:
    def __init__(self, messages: list[aiohttp.WSMessage]) -> None:
        self._messages = messages
        self.sent: list[str] = []

    async def receive(self, timeout: float | None = None) -> aiohttp.WSMessage:  # noqa: ASYNC109
        if self._messages:
            return self._messages.pop(0)
        return _msg(aiohttp.WSMsgType.CLOSED, None)

    async def send_str(self, data: str) -> None:
        self.sent.append(data)


def _session(ws: _FakeWS) -> MagicMock:
    session = MagicMock()

    @asynccontextmanager
    async def ws_connect(url: str, **_kwargs):  # type: ignore[no-untyped-def]
        session.ws_url = url
        yield ws

    session.ws_connect = ws_connect
    return session


_STREAM = "wss://vtm.example:20006/live?dev=BK1&chn=1&stream=2&checkCode=x&ssn=ssn"
_HELLO = _msg(aiohttp.WSMsgType.TEXT, json.dumps({"version": "1.0", "cipherSuite": "0"}))


async def test_capture_sends_realplay_on_hello_and_buffers_video() -> None:
    ws = _FakeWS(
        [
            _HELLO,
            _msg(aiohttp.WSMsgType.TEXT, json.dumps({"statusCode": 0, "errorCode": 1})),
            _msg(aiohttp.WSMsgType.BINARY, b"IMKH" + b"\x00" * 36),
            _msg(aiohttp.WSMsgType.BINARY, b"frame-bytes"),
        ]
    )
    session = _session(ws)
    data = await async_capture_ps(session, _STREAM)
    assert b"frame-bytes" in data
    assert session.ws_url.endswith("?version=0.1&cipherSuites=0")
    assert "/live" not in session.ws_url.split("?")[0]
    (sent,) = ws.sent
    payload = json.loads(sent)
    assert payload["cmd"] == "realplay"
    assert payload["url"].startswith("/live?")
    assert "ssn=ssn" in payload["url"]


async def test_capture_raises_on_stream_error() -> None:
    ws = _FakeWS(
        [
            _HELLO,
            _msg(
                aiohttp.WSMsgType.TEXT,
                json.dumps({"statusCode": 1, "errorCode": 5405, "errorMsg": "get stream error"}),
            ),
        ]
    )
    with pytest.raises(EzvizCloudError, match="5405"):
        await async_capture_ps(_session(ws), _STREAM)


async def test_capture_raises_when_no_video_arrives() -> None:
    ws = _FakeWS([_HELLO])
    with pytest.raises(EzvizCloudError, match="asleep"):
        await async_capture_ps(_session(ws), _STREAM)


async def test_capture_skips_non_json_text_and_stops_at_max_bytes() -> None:
    ws = _FakeWS(
        [
            _msg(aiohttp.WSMsgType.TEXT, "not json"),
            _HELLO,
            _msg(aiohttp.WSMsgType.BINARY, b"a" * 10),
            _msg(aiohttp.WSMsgType.BINARY, b"never read"),
        ]
    )
    assert await async_capture_ps(_session(ws), _STREAM, max_bytes=5) == b"a" * 10


async def test_capture_stops_when_the_receive_times_out() -> None:
    ws = _FakeWS([_HELLO, _msg(aiohttp.WSMsgType.BINARY, b"frame")])
    ws.receive = AsyncMock(side_effect=[_HELLO, _msg(aiohttp.WSMsgType.BINARY, b"f"), TimeoutError])
    assert await async_capture_ps(_session(ws), _STREAM) == b"f"


async def test_capture_gives_up_after_the_wake_timeout() -> None:
    with pytest.raises(EzvizCloudError, match="asleep"):
        await async_capture_ps(_session(_FakeWS([_HELLO])), _STREAM, wake_timeout=0)


async def test_capture_stops_after_capture_seconds() -> None:
    ws = _FakeWS(
        [_HELLO, _msg(aiohttp.WSMsgType.BINARY, b"f"), _msg(aiohttp.WSMsgType.BINARY, b"late")]
    )
    assert await async_capture_ps(_session(ws), _STREAM, capture_seconds=0) == b"f"


async def test_capture_wraps_websocket_errors() -> None:
    session = MagicMock()
    session.ws_connect = MagicMock(side_effect=aiohttp.ClientError("refused"))
    with pytest.raises(EzvizCloudError, match="refused"):
        await async_capture_ps(session, _STREAM)


def test_decrypt_uses_pyezvizapi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pyezvizapi.cloud_stream.decrypt_hikvision_ps_video", lambda ps, code: ps + code.encode()
    )
    assert _decrypt(b"ps-", "KEY") == b"ps-KEY"
