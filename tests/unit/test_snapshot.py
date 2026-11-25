"""Server-side video: WebSocket play, cutting into packs, decrypt, ffmpeg."""

from __future__ import annotations

import inspect
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.ezviz_cloud.api import EzvizCloudError
from custom_components.ezviz_cloud.snapshot import (
    EzvizCloudDecodeError,
    PackSplitter,
    RtpToPs,
    _decrypt,
    _packets,
    async_iter_stream,
    async_ps_to_jpeg,
    async_ps_to_mp4,
    decrypt_packs,
    keep_video,
)

IMKH = b"IMKH" + b"\x00" * 36
# 14-byte pack header; the last byte's low 3 bits say "no stuffing follows".
PACK = b"\x00\x00\x01\xba" + b"\x44\x00\x37\xc6\x84\x01\x00\xf5\xc7\xf8"


def _pes(payload: bytes, stream_id: int = 0xE0) -> bytes:
    """A minimal PES packet (video stream 0xE0 unless told) with a zero-length header."""
    body = b"\x80\x00\x00" + payload
    return bytes([0, 0, 1, stream_id]) + len(body).to_bytes(2, "big") + body


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
        "pyezvizapi.decrypt_hikvision_ps_video",
        lambda ps, code, nalu_header_size: ps + code.encode() + bytes([nalu_header_size]),
    )
    assert _decrypt(b"ps-", "KEY", codec) == b"ps-KEY" + bytes([header])


def test_pyezvizapi_still_has_the_decrypt_we_call() -> None:
    from pyezvizapi import decrypt_hikvision_ps_video

    params = inspect.signature(decrypt_hikvision_ps_video).parameters
    assert "nalu_header_size" in params
    assert len([p for p in params.values() if p.default is p.empty]) == 2


def test_decrypt_packs_cuts_three_packs_back_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "custom_components.ezviz_cloud.snapshot._decrypt", lambda ps, code, codec: ps.upper()
    )
    assert decrypt_packs([b"ab", b"cde", b"f", b"gh"], "KEY", "h264") == [
        b"AB",
        b"CDE",
        b"F",
        b"GH",
    ]


# A pack header whose last byte announces two stuffing bytes after it.
STUFFED_PACK = PACK[:13] + bytes([0xF8 | 2]) + b"\xff\xff"


def test_splitter_skips_the_stuffing_after_a_pack_header() -> None:
    first, frame = STUFFED_PACK + _psm(0x1B) + _pes(b"key"), STUFFED_PACK + _pes(b"p")
    stream = first + frame + PACK
    whole = _collect(PackSplitter(skip_first_group=False), stream)
    assert whole == [(first, True), (frame, False)]
    for size in (1, 5, 15):
        chunks = [stream[i : i + size] for i in range(0, len(stream), size)]
        splitter = PackSplitter(skip_first_group=False)
        assert _collect(splitter, *chunks) == whole
        assert splitter.codec == "h264"


def test_splitter_reads_the_codec_past_the_program_stream_info() -> None:
    info = b"\x05\x01\xaa"  # a descriptor before the list of streams
    entries = bytes([0x1B, 0xE0]) + b"\x00\x00"
    body = (
        b"\x80\x01"
        + len(info).to_bytes(2, "big")
        + info
        + len(entries).to_bytes(2, "big")
        + entries
    )
    psm = b"\x00\x00\x01\xbc" + len(body).to_bytes(2, "big") + body
    splitter = PackSplitter(skip_first_group=False)
    splitter.feed(PACK + psm + _pes(b"v") + PACK)
    assert splitter.codec == "h264"


async def test_stream_sends_realplay_only_once() -> None:
    status = _msg(aiohttp.WSMsgType.TEXT, json.dumps({"statusCode": 0}))
    ws = _FakeWS([status, _HELLO, _HELLO, _msg(aiohttp.WSMsgType.BINARY, b"IMKH")])
    assert await _read(_session(ws)) == [b"IMKH"]
    assert len(ws.sent) == 1


def test_keep_video_drops_the_other_video_streams_only() -> None:
    first, second, audio = _pes(b"one"), _pes(b"two", 0xE1), _pes(b"snd", 0xC0)
    pack = PACK + _psm() + first + audio + second
    assert keep_video(pack, 0xE1) == PACK + _psm() + audio + second
    assert keep_video(pack, 0xE0) == PACK + _psm() + first + audio
    # A stream with one video track loses it when another is asked for: nothing else.
    assert keep_video(PACK + first + audio, 0xE1) == PACK + audio
    # Not a pack: left alone.
    assert keep_video(b"junk", 0xE1) == b"junk"
    assert keep_video(PACK + b"junk-after-header", 0xE1) == PACK + b"junk-after-header"


def test_splitter_counts_what_each_stream_carried() -> None:
    idr = b"\x00\x00\x00\x01\x26\x01"  # HEVC NAL type 19
    trail = b"\x00\x00\x01\x02\x01"  # HEVC NAL type 1, short start code
    stream = (
        PACK + _psm() + _pes(idr) + _pes(b"more of it") + _pes(idr, 0xE1)
        + PACK + _pes(trail) + _pes(b"snd", 0xC0)
        + PACK
    )  # fmt: skip
    splitter = PackSplitter(skip_first_group=False)
    # Fed in two halves: a pack that is parsed twice is still counted once.
    _collect(splitter, stream[:40], stream[40:])
    assert splitter.stats[0xE0] == [3, len(_pes(idr)) + len(_pes(b"more of it")) + len(_pes(trail))]
    assert splitter.stats[0xE1] == [1, len(_pes(idr, 0xE1))]
    assert splitter.stats[0xC0][0] == 1
    assert splitter.nals == {0xE0: {19, 1}, 0xE1: {19}}
    summary = splitter.summary()
    assert "e0: 3 packets" in summary
    assert "NAL types [1, 19]" in summary
    assert summary.index("bc:") < summary.index("c0:") < summary.index("e0:") < summary.index("e1:")


def test_splitter_reads_h264_nal_types() -> None:
    splitter = PackSplitter(skip_first_group=False)
    _collect(splitter, PACK + _psm(0x1B) + _pes(b"\x00\x00\x00\x01\x65") + PACK)
    assert splitter.nals == {0xE0: {5}}


# RTP as some cameras (the EP4) send it: fixed source id, video on PT 96.
VPS, IDR = b"\x40\x01\x0c", b"\x26\x01\xaf\x00"  # H.265 NAL units: VPS (32), IDR (19)
P_FRAME = b"\x02\x01\xd0"  # H.265 non-key slice (1)


def _rtp(
    payload: bytes,
    *,
    pt: int = 96,
    seq: int = 1,
    ts: int = 3000,
    marker: bool = True,
    ext: bytes | None = None,
    profile: int = 1,
    pad: int = 0,
) -> bytes:
    b0 = 0x80 | (0x10 if ext is not None else 0) | (0x20 if pad else 0)
    head = bytes((b0, (0x80 if marker else 0) | pt)) + seq.to_bytes(2, "big")
    head += ts.to_bytes(4, "big") + b"\x55\x66\x77\x88"
    if ext is not None:
        head += profile.to_bytes(2, "big") + (len(ext) // 4).to_bytes(2, "big") + ext
    return head + payload + (bytes(pad - 1) + bytes((pad,)) if pad else b"")


def _rtp_nals(ps: bytes) -> list[bytes]:
    """The NAL units in the video PES packets of RtpToPs output."""
    es = b""
    for pack in ps.split(b"\x00\x00\x01\xba")[1:]:
        for sid, start, end in _packets(b"\x00\x00\x01\xba" + pack):
            if sid == 0xE0:
                body = (b"\x00\x00\x01\xba" + pack)[start:end]
                es += body[9 + body[8] :]
    return [n for n in es.split(b"\x00\x00\x00\x01") if n]


def test_rtp_starts_only_on_the_fixed_source_id() -> None:
    assert RtpToPs.starts(_rtp(IDR))
    assert not RtpToPs.starts(IMKH)
    assert not RtpToPs.starts(_rtp(IDR)[:11])


def test_splitter_turns_rtp_into_packs_with_a_stream_map() -> None:
    descriptor = bytes((0x45, 2, 0x24, 96))
    splitter = PackSplitter(skip_first_group=False)
    out = _collect(
        splitter,
        _rtp(b"", pt=112, ext=descriptor),
        _rtp(VPS, seq=2, marker=False),
        _rtp(IDR, seq=3),
        _rtp(b"\x00" * 160, pt=8, seq=4),  # audio, dropped
        _rtp(P_FRAME, seq=5, ts=6000),
        _rtp(P_FRAME, seq=6, ts=9000),
    )
    assert [key for _, key in out] == [True, False]
    assert splitter.codec == "hevc"
    assert _rtp_nals(out[0][0]) == [VPS, IDR]
    assert "RTP payload types {8: 1, 96: 4, 112: 1}, video 96 hevc" in splitter.summary()


def test_rtp_pts_follow_the_rtp_clock() -> None:
    rtp = RtpToPs()
    first = rtp.feed(_rtp(IDR, ts=0xFFFFF000))
    second = rtp.feed(_rtp(P_FRAME, seq=2, ts=0x00000FA0))  # the clock wrapped
    assert _pts(first) == 90_000
    assert _pts(second) == 90_000 + 0x1FA0


def _pts(ps: bytes) -> int:
    i = ps.index(b"\x00\x00\x01\xe0") + 9
    b = ps[i : i + 5]
    return ((b[0] >> 1) & 7) << 30 | b[1] << 22 | (b[2] >> 1) << 15 | b[3] << 7 | b[4] >> 1


def test_rtp_reassembles_fragments_and_aggregates() -> None:
    rtp = RtpToPs()
    big = b"\x26\x01" + bytes(range(256)) * 300  # an IDR larger than one PES packet
    body = big[2:]
    fu_start = b"\x62\x01\x93" + body[:40000]
    fu_end = b"\x62\x01\x53" + body[40000:]
    ap = b"\x60\x01" + len(VPS).to_bytes(2, "big") + VPS + b"\x00\x03" + b"\x42\x01\x01"
    out = rtp.feed(_rtp(ap, marker=False))
    out += rtp.feed(_rtp(fu_start, seq=2, marker=False))
    out += rtp.feed(_rtp(b"\x62\x01\x13" + b"", seq=3, marker=False, pad=2))
    out += rtp.feed(_rtp(fu_end, seq=4))
    assert out.count(b"\x00\x00\x01\xe0") == 4  # VPS, PPS, and the IDR cut in two
    assert _rtp_nals(out) == [VPS, b"\x42\x01\x01", big]


def test_rtp_drops_a_fragment_with_a_gap_before_it() -> None:
    rtp = RtpToPs()
    assert rtp.feed(_rtp(b"\x62\x01\x93abc", marker=False)) == b""
    assert rtp.feed(_rtp(b"\x62\x01\x53def", seq=3)) == b""  # seq 2 lost
    assert rtp.dropped == 2  # the open fragment, then the orphan end


def test_rtp_reads_h264_without_a_descriptor() -> None:
    rtp = RtpToPs()
    sps, idr = b"\x67\x4d\x00\x1f", b"\x65\x88\x84"
    stap = b"\x18" + len(sps).to_bytes(2, "big") + sps
    out = rtp.feed(_rtp(stap, marker=False))
    out += rtp.feed(_rtp(b"\x7c\x85" + idr[1:2], seq=2, marker=False))
    out += rtp.feed(_rtp(b"\x7c\x45" + idr[2:], seq=3))
    assert rtp.codec == "h264"
    assert b"\x00\x00\x01\xbc" in out
    assert b"\x1b\xe0" in out  # stream map says H.264
    assert _rtp_nals(out) == [sps, idr]


def test_rtp_waits_for_a_packet_that_names_the_codec() -> None:
    rtp = RtpToPs()
    sps = b"\x67\x4d\x00\x1f" + bytes(252)  # 256 bytes: the STAP-A size reads 01 00
    assert rtp.feed(_rtp(b"\x7c\x01abc")) == b""  # a middle fragment, either codec
    assert rtp.feed(_rtp(b"\x61\x01")) == b""  # an H.264 slice with an H.265-like header
    assert rtp.feed(_rtp(b"\x80\x01\x00")) == b""  # forbidden bit set
    assert rtp.feed(_rtp(b"\x41\x01\x9a")) == b""  # H.264 slice; as H.265 its layer isn't 0
    assert rtp.codec is None
    out = rtp.feed(_rtp(b"\x18" + len(sps).to_bytes(2, "big") + sps, seq=3))
    assert rtp.codec == "h264"
    assert _rtp_nals(out) == [sps]
    aud_first = RtpToPs()  # an access unit delimiter ahead of the parameter set
    aud_first.feed(_rtp(b"\x18\x00\x02\x09\xf0" + len(sps).to_bytes(2, "big") + sps))
    assert aud_first.codec == "h264"
    aud_first = RtpToPs()
    aud_first.feed(_rtp(b"\x60\x01\x00\x03\x46\x01\x50\x00\x03" + VPS))
    assert aud_first.codec == "hevc"
    fu_a = RtpToPs()
    fu_a.feed(_rtp(b"\x7c\x85\x88"))  # first fragment of an IDR
    assert fu_a.codec == "h264"


def test_rtp_starts_every_nal_unit_in_its_own_pes_packet() -> None:
    rtp = RtpToPs()
    first = b"\x26\x01" + bytes(59_992)  # its end leaves the next start code across 60 000
    nals = [first, b"\x02\x01\xd0"]
    ap = b"\x60\x01" + b"".join(len(n).to_bytes(2, "big") + n for n in nals)
    out = rtp.feed(_rtp(ap))
    payloads = [p[5 + p[4] :] for p in out.split(b"\x00\x00\x01\xe0")[1:]]
    assert [p[:4] for p in payloads] == [b"\x00\x00\x00\x01"] * 2
    assert _rtp_nals(out) == nals


def test_rtp_takes_the_video_route_only_from_a_real_descriptor() -> None:
    # Audio extensions (profile 0x4000) aren't descriptors, even when their bytes
    # read like one; H.264 never sits on a static payload type like 15.
    rtp = RtpToPs()
    rtp.feed(_rtp(b"", pt=104, ext=bytes((0x45, 2, 0x1B, 15)), profile=0x4000))
    rtp.feed(_rtp(b"", pt=112, ext=bytes((0x45, 2, 0x1B, 15))))
    assert rtp.video_pt is None
    assert rtp.feed(_rtp(IDR)) != b""  # PT 96 still read as video
    assert "descriptor 45021b0f" in rtp.summary()


def test_rtp_ignores_what_it_cannot_read() -> None:
    rtp = RtpToPs()
    assert rtp.feed(b"\x00" * 20) == b""  # not RTP v2
    assert rtp.feed(_rtp(b"", pt=96)) == b""  # empty payload
    assert rtp.feed(_rtp(b"", ext=bytes((0x45, 2, 0x99, 97)))) == b""  # unknown codec
    assert rtp.video_pt is None
    rtp.feed(_rtp(IDR))
    assert rtp.feed(_rtp(b"\x62\x01")) == b""  # fragment too short to have a header
    assert rtp.feed(_rtp(b"\x62\x01\x13x", seq=2)) == b""  # continuation without a start


def test_rtp_closes_a_picture_when_the_timestamp_moves_on() -> None:
    rtp = RtpToPs()
    assert rtp.feed(_rtp(IDR, marker=False)) == b""
    out = rtp.feed(_rtp(P_FRAME, seq=2, ts=6000, marker=False))
    assert _rtp_nals(out) == [IDR]
