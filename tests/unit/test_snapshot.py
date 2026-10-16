"""Server-side photo capture: WebSocket play, PS demux, decode."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.ezviz_cloud.api import EzvizCloudError
from custom_components.ezviz_cloud.snapshot import (
    _decrypt,
    _demux_ps,
    async_annexb_to_jpeg,
    async_capture_ps,
    decrypt_and_demux,
)


def _pes(payload: bytes) -> bytes:
    """A minimal video PES packet (stream id 0xE0) with a zero-length header."""
    header = b"\x80\x00\x00"  # flags, flags, header-data-length = 0
    body = header + payload
    return b"\x00\x00\x01\xe0" + len(body).to_bytes(2, "big") + body


def _pack(*pes: bytes) -> bytes:
    """An MPEG-PS pack: IMKH prefix, pack header, then the PES packets."""
    # 14-byte pack header; the last byte's low 3 bits say "no stuffing follows".
    pack_header = b"\x00\x00\x01\xba" + b"\x44\x00\x37\xc6\x84\x01\x00\xf5\xc7\xf8"
    return b"IMKH" + b"\x00" * 36 + pack_header + b"".join(pes)


def test_demux_strips_imkh_and_concatenates_video_payloads() -> None:
    annexb = b"\x00\x00\x00\x01\x40\x01payload\x00\x00\x00\x01\x26\x01frame"
    ps = _pack(_pes(annexb[:14]), _pes(annexb[14:]))
    assert _demux_ps(ps) == (annexb, "hevc")


def test_demux_ignores_non_video_streams() -> None:
    audio = b"\x00\x00\x01\xc0\x00\x05\x80\x00\x00ab"  # stream id 0xC0
    ps = _pack(_pes(b"\x00\x00\x00\x01v")) + audio
    assert _demux_ps(ps)[0] == b"\x00\x00\x00\x01v"


def test_decrypt_and_demux_without_code_skips_decryption() -> None:
    ps = _pack(_pes(b"\x00\x00\x00\x01v"))
    assert decrypt_and_demux(ps, None)[0] == b"\x00\x00\x00\x01v"


def test_decrypt_and_demux_with_code_decrypts_first(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        "custom_components.ezviz_cloud.snapshot._decrypt",
        lambda ps, code: calls.append(code) or ps,
    )
    assert decrypt_and_demux(_pack(_pes(b"\x00\x00\x00\x01v")), "SECRET")[0] == (
        b"\x00\x00\x00\x01v"
    )
    assert calls == ["SECRET"]


async def test_annexb_to_jpeg_runs_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"\xff\xd8the-jpeg", b""))
    created = {}

    async def fake_exec(*args, **_kwargs):  # type: ignore[no-untyped-def]
        created["args"] = args
        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    jpeg = await async_annexb_to_jpeg(b"\x00\x00\x00\x01v", "hevc", "/usr/bin/ffmpeg")
    assert jpeg == b"\xff\xd8the-jpeg"
    assert created["args"][0] == "/usr/bin/ffmpeg"
    assert proc.communicate.await_args.args == (b"\x00\x00\x00\x01v",)


async def test_annexb_to_jpeg_raises_when_ffmpeg_decodes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"", b"Invalid data found"))

    async def fake_exec(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    with pytest.raises(EzvizCloudError, match="Invalid data found"):
        await async_annexb_to_jpeg(b"bad", "hevc", "/usr/bin/ffmpeg")


async def test_annexb_to_jpeg_kills_a_hung_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock()
    proc.communicate = AsyncMock(side_effect=TimeoutError)
    proc.wait = AsyncMock()

    async def fake_exec(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    with pytest.raises(EzvizCloudError, match="in time"):
        await async_annexb_to_jpeg(b"\x00\x00\x00\x01v", "hevc", "/usr/bin/ffmpeg")
    proc.kill.assert_called_once()


def test_demux_stops_at_a_truncated_pack_header() -> None:
    ps = _pack(_pes(b"\x00\x00\x00\x01v")) + b"\x00\x00\x01\xba\x44\x00"
    assert _demux_ps(ps)[0] == b"\x00\x00\x00\x01v"


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


def _psm(stream_type: int, other: bytes = b"") -> bytes:
    """A program stream map listing ``other`` entries, then the video stream (0xE0)."""
    entries = other + bytes([stream_type, 0xE0]) + b"\x00\x00"
    body = b"\x80\x01\x00\x00" + len(entries).to_bytes(2, "big") + entries
    return b"\x00\x00\x01\xbc" + len(body).to_bytes(2, "big") + body


@pytest.mark.parametrize(("stream_type", "codec"), [(0x1B, "h264"), (0x24, "hevc"), (0x99, "hevc")])
def test_demux_reads_the_codec_from_the_stream_map(stream_type: int, codec: str) -> None:
    audio = b"\x0f\xc0\x00\x02ab"  # an audio entry with 2 bytes of descriptors, listed first
    ps = _pack(_pes(b"\x00\x00\x00\x01v")) + _psm(stream_type, audio)
    assert _demux_ps(ps) == (b"\x00\x00\x00\x01v", codec)


def test_demux_resyncs_past_garbage() -> None:
    ps = b"junk" + _pes(b"\x00\x00\x00\x01v")[0:] + b"trailing-junk-no-start-code"
    assert _demux_ps(ps)[0] == b"\x00\x00\x00\x01v"


def test_demux_keeps_the_default_when_the_stream_map_lists_no_video() -> None:
    entries = b"\x0f\xc0\x00\x00"  # audio only
    body = b"\x80\x01\x00\x00" + len(entries).to_bytes(2, "big") + entries
    psm = b"\x00\x00\x01\xbc" + len(body).to_bytes(2, "big") + body
    assert _demux_ps(_pack(_pes(b"\x00\x00\x00\x01v")) + psm)[1] == "hevc"
