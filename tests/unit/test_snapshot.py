"""Server-side video: WebSocket play, cutting into packs, decrypt, ffmpeg."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.ezviz_cloud.api import EzvizCloudError
from custom_components.ezviz_cloud.snapshot import (
    EzvizCloudDecodeError,
    PackSplitter,
    _decrypt,
    async_iter_stream,
    async_ps_to_jpeg,
    async_ps_to_mp4,
    decrypt_packs,
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


def _collect(splitter: PackSplitter, *chunks: bytes) -> list[tuple[bytes, bool]]:
    out: list[tuple[bytes, bool]] = []
    for chunk in chunks:
        out += splitter.feed(chunk)
    return out


def test_splitter_skips_the_first_group_and_flags_keyframes() -> None:
    first, live, frame = _gop(b"stale"), _gop(b"key"), PACK + _pes(b"p")
    splitter = PackSplitter(skip_first_group=True)
    # A pack is only complete once the next one starts.
    assert _collect(splitter, IMKH + first + live + frame + PACK) == [
        (live, True),
        (frame, False),
    ]


def test_splitter_keeps_everything_without_skip_and_reads_the_codec() -> None:
    first, frame = _gop(b"key", 0x1B), PACK + _pes(b"p")
    splitter = PackSplitter(skip_first_group=False)
    assert _collect(splitter, first + frame + PACK) == [(first, True), (frame, False)]
    assert splitter.codec == "h264"


@pytest.mark.parametrize(("stream_type", "codec"), [(0x1B, "h264"), (0x24, "hevc"), (0x99, "hevc")])
def test_splitter_reads_the_codec_past_other_streams(stream_type: int, codec: str) -> None:
    audio = b"\x0f\xc0\x00\x02ab"  # an audio entry with 2 bytes of descriptors, listed first
    splitter = PackSplitter(skip_first_group=False)
    splitter.feed(PACK + _psm(stream_type, audio) + _pes(b"v") + PACK)
    assert splitter.codec == codec


def test_splitter_keeps_the_codec_when_the_stream_map_lists_no_video() -> None:
    entries = b"\x0f\xc0\x00\x00"  # audio only
    body = b"\x80\x01\x00\x00" + len(entries).to_bytes(2, "big") + entries
    psm = b"\x00\x00\x01\xbc" + len(body).to_bytes(2, "big") + body
    splitter = PackSplitter(skip_first_group=False)
    splitter.feed(_gop(b"k", 0x1B) + PACK + psm + PACK)
    assert splitter.codec == "h264"


def test_splitter_reassembles_packs_split_anywhere() -> None:
    stream = IMKH + _gop(b"a") + _gop(b"b") + PACK + _pes(b"c") + PACK
    whole = _collect(PackSplitter(skip_first_group=False), stream)
    for size in (1, 3, 7, 40):
        chunks = [stream[i : i + size] for i in range(0, len(stream), size)]
        assert _collect(PackSplitter(skip_first_group=False), *chunks) == whole


def test_splitter_resyncs_after_garbage() -> None:
    frame = PACK + _pes(b"p")
    splitter = PackSplitter(skip_first_group=False)
    out = _collect(splitter, _gop(b"k") + b"junk!" + b"more" + frame + PACK)
    # The pack that holds the garbage is dropped; the next one comes through.
    assert out == [(frame, False)]
    # The pending pack runs into garbage too: dropped, and the next frame survives.
    assert _collect(splitter, b"no start code here", frame, PACK) == [(frame, False)]


def test_splitter_trusts_packet_lengths() -> None:
    fake_map = b"\x00\x00\x01\xbc\x00\x00"
    frame = PACK + _pes(fake_map)
    assert _collect(PackSplitter(skip_first_group=False), frame + PACK) == [(frame, False)]


def test_splitter_waits_for_the_whole_imkh_header() -> None:
    splitter = PackSplitter(skip_first_group=False)
    assert splitter.feed(b"IM") == []
    assert splitter.feed(IMKH[2:20]) == []
    frame = _gop(b"k")
    assert splitter.feed(IMKH[20:] + frame + PACK) == [(frame, True)]


def test_decrypt_packs_decrypts_together_and_cuts_back(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        "custom_components.ezviz_cloud.snapshot._decrypt",
        lambda ps, code, codec: calls.append((ps, code, codec)) or ps.upper(),
    )
    assert decrypt_packs([b"ab", b"cde"], "KEY", "h264") == [b"AB", b"CDE"]
    assert calls == [(b"abcde", "KEY", "h264")]
    assert decrypt_packs([b"ab"], None, "hevc") == [b"ab"]


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
    with pytest.raises(EzvizCloudDecodeError, match="Invalid data found"):
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


async def _read(session: MagicMock, **kwargs: float) -> list[bytes]:
    return [data async for data in async_iter_stream(session, _STREAM, **kwargs)]


async def test_stream_sends_realplay_on_hello_and_yields_video() -> None:
    ws = _FakeWS(
        [
            _HELLO,
            _msg(aiohttp.WSMsgType.TEXT, json.dumps({"statusCode": 0, "errorCode": 1})),
            _msg(aiohttp.WSMsgType.BINARY, b"IMKH"),
            _msg(aiohttp.WSMsgType.BINARY, b"frame-bytes"),
        ]
    )
    session = _session(ws)
    assert await _read(session) == [b"IMKH", b"frame-bytes"]
    assert session.ws_url.endswith("?version=0.1&cipherSuites=0")
    assert "/live" not in session.ws_url.split("?")[0]
    (sent,) = ws.sent
    payload = json.loads(sent)
    assert payload["cmd"] == "realplay"
    assert payload["url"].startswith("/live?")
    assert "ssn=ssn" in payload["url"]


async def test_stream_raises_on_stream_error() -> None:
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
        await _read(_session(ws))


async def test_stream_raises_when_no_video_arrives() -> None:
    with pytest.raises(EzvizCloudError, match="asleep"):
        await _read(_session(_FakeWS([_HELLO])))


async def test_stream_skips_non_json_text() -> None:
    ws = _FakeWS(
        [_msg(aiohttp.WSMsgType.TEXT, "not json"), _HELLO, _msg(aiohttp.WSMsgType.BINARY, b"a")]
    )
    assert await _read(_session(ws)) == [b"a"]


async def test_stream_ends_when_the_receive_times_out() -> None:
    ws = _FakeWS([])
    ws.receive = AsyncMock(side_effect=[_HELLO, _msg(aiohttp.WSMsgType.BINARY, b"f"), TimeoutError])
    assert await _read(_session(ws)) == [b"f"]
    # Before any video, the wait is the wake timeout; after it, the idle timeout.
    timeouts = [c.kwargs["timeout"] for c in ws.receive.await_args_list]
    assert timeouts == [20.0, 20.0, 10.0]


async def test_stream_gives_up_after_the_wake_timeout() -> None:
    ws = _FakeWS([])
    ws.receive = AsyncMock(side_effect=[_HELLO, TimeoutError])
    with pytest.raises(EzvizCloudError, match="asleep"):
        await _read(_session(ws), wake_timeout=0)


async def test_stream_wraps_websocket_errors() -> None:
    session = MagicMock()
    session.ws_connect = MagicMock(side_effect=aiohttp.ClientError("refused"))
    with pytest.raises(EzvizCloudError, match="refused"):
        await _read(session)


@pytest.mark.parametrize(("codec", "header"), [("hevc", 2), ("h264", 1)])
def test_decrypt_uses_pyezvizapi(monkeypatch: pytest.MonkeyPatch, codec: str, header: int) -> None:
    monkeypatch.setattr(
        "pyezvizapi.cloud_stream.decrypt_hikvision_ps_video",
        lambda ps, code, nalu_header_size: ps + code.encode() + bytes([nalu_header_size]),
    )
    assert _decrypt(b"ps-", "KEY", codec) == b"ps-KEY" + bytes([header])
