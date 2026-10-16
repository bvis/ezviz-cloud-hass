"""Server-side photo capture: stream resolve, WebSocket play, PS demux, decode."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.ezviz_cloud.api import EzvizCloudError
from custom_components.ezviz_cloud.snapshot import (
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
    assert _demux_ps(ps) == annexb


def test_demux_ignores_non_video_streams() -> None:
    audio = b"\x00\x00\x01\xc0\x00\x05\x80\x00\x00ab"  # stream id 0xC0
    ps = _pack(_pes(b"\x00\x00\x00\x01v")) + audio
    assert _demux_ps(ps) == b"\x00\x00\x00\x01v"


def test_decrypt_and_demux_without_code_skips_decryption() -> None:
    ps = _pack(_pes(b"\x00\x00\x00\x01v"))
    assert decrypt_and_demux(ps, None) == b"\x00\x00\x00\x01v"


def test_decrypt_and_demux_with_code_decrypts_first(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        "custom_components.ezviz_cloud.snapshot._decrypt",
        lambda ps, code: calls.append(code) or ps,
    )
    assert decrypt_and_demux(_pack(_pes(b"\x00\x00\x00\x01v")), "SECRET") == b"\x00\x00\x00\x01v"
    assert calls == ["SECRET"]


async def test_annexb_to_jpeg_runs_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"\xff\xd8the-jpeg", b""))
    created = {}

    async def fake_exec(*args, **_kwargs):  # type: ignore[no-untyped-def]
        created["args"] = args
        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    jpeg = await async_annexb_to_jpeg(b"\x00\x00\x00\x01v", "/usr/bin/ffmpeg")
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
        await async_annexb_to_jpeg(b"bad", "/usr/bin/ffmpeg")


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


def _session(stream_url: str, ws: _FakeWS) -> MagicMock:
    session = MagicMock()

    @asynccontextmanager
    async def post(url: str, **_kwargs):  # type: ignore[no-untyped-def]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = AsyncMock(
            return_value={"code": "200", "data": {"url": stream_url, "token": "ssn"}}
        )
        yield resp

    @asynccontextmanager
    async def ws_connect(url: str, **_kwargs):  # type: ignore[no-untyped-def]
        session.ws_url = url
        yield ws

    session.post = post
    session.ws_connect = ws_connect
    return session


_STREAM = "wss://vtm.example:20006/live?dev=BK1&chn=1&stream=2&checkCode=x"
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
    session = _session(_STREAM, ws)
    data = await async_capture_ps(session, "https://d", "tok", "BK1", 1, "CODE")
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
        await async_capture_ps(_session(_STREAM, ws), "https://d", "tok", "BK1", 1, "CODE")


async def test_capture_raises_when_no_video_arrives() -> None:
    ws = _FakeWS([_HELLO])
    with pytest.raises(EzvizCloudError, match="asleep"):
        await async_capture_ps(_session(_STREAM, ws), "https://d", "tok", "BK1", 1, "CODE")


async def test_resolve_stream_reports_platform_error() -> None:
    session = MagicMock()

    @asynccontextmanager
    async def post(url: str, **_kwargs):  # type: ignore[no-untyped-def]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = AsyncMock(return_value={"code": "60019", "msg": "nope"})
        yield resp

    session.post = post
    with pytest.raises(EzvizCloudError, match="60019"):
        await async_capture_ps(session, "https://d", "tok", "BK1", 1, "CODE")
