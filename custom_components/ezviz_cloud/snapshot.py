"""Server-side video: play the live stream, cut and decrypt it, hand it to ffmpeg.

The card decrypts and plays video in the browser; this does the same without a
browser, for the live camera and the photo and clip buttons (``live.py`` shares
one stream between them). It plays the same ``ezopen`` live stream (its URL
comes from ``EzvizCloudApi.async_live_url``), decrypts the NAL bodies with
``pyezvizapi`` (the verification code is the AES key) and lets ffmpeg read the
MPEG-PS: one frame to JPEG for a photo, a stream copy to MP4 for a clip.

The stream opens with a group of pictures that doesn't decode and carries no
on-screen clock: with a code that one is skipped, so video starts at the first
live keyframe.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterator

import aiohttp

from .api import EzvizCloudError

_LOGGER = logging.getLogger(__name__)


class EzvizCloudDecodeError(EzvizCloudError):
    """ffmpeg found no frame it could decode: a wrong verification code, or a broken stream."""


# The player handshake: protocol 0.1, no cipher suite (the NAL bodies carry
# their own AES, keyed by the verification code).
_WS_QUERY = "?version=0.1&cipherSuites=0"
_FFMPEG_TIMEOUT = 15
_IMKH_HEADER = 40  # EZVIZ prefixes the MPEG-PS stream with a 40-byte "IMKH" header.
# MPEG-PS stream types in the program stream map.
_CODECS = {0x1B: "h264", 0x24: "hevc"}
_DEFAULT_CODEC = "hevc"


async def async_iter_stream(
    session: aiohttp.ClientSession,
    stream_url: str,
    *,
    wake_timeout: float = 20.0,
    idle_timeout: float = 10.0,
) -> AsyncIterator[bytes]:
    """Play the live stream and yield its raw MPEG-PS as it arrives.

    Waits up to ``wake_timeout`` for the first video byte (the camera may be
    asleep) and ends after ``idle_timeout`` without one, or when the cloud closes
    the stream. Closing the generator closes the stream.
    """
    address, _, query = stream_url.partition("?")
    host = address.replace("/live", "")
    play_param = "/live?" + query
    started = False
    try:
        async with session.ws_connect(host + _WS_QUERY, max_msg_size=0) as ws:
            sent = False
            while True:
                try:
                    msg = await ws.receive(timeout=idle_timeout if started else wake_timeout)
                except TimeoutError:
                    break
                if msg.type is aiohttp.WSMsgType.TEXT:
                    try:
                        info = json.loads(msg.data)
                    except ValueError:
                        continue
                    if not sent and "cipherSuite" in info:
                        await ws.send_str(
                            json.dumps({"sequence": 0, "cmd": "realplay", "url": play_param})
                        )
                        sent = True
                    elif info.get("statusCode") == 1:
                        raise EzvizCloudError(
                            f"Stream error {info.get('errorCode')}: {info.get('errorMsg')}"
                        )
                elif msg.type is aiohttp.WSMsgType.BINARY:
                    started = True
                    yield msg.data
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
    except aiohttp.ClientError as err:
        raise EzvizCloudError(f"Live stream failed: {err}") from err
    if not started:
        raise EzvizCloudError("No video received; the camera may be asleep")


class PackSplitter:
    """Cuts the live MPEG-PS into packs, one frame each, as its bytes arrive.

    A pack is complete once the next one starts; a pack carrying a program stream
    map (0xBC) opens a group of pictures, so it holds a keyframe, and the map
    names the codec. Packet lengths are trusted, so payload bytes are never
    mistaken for headers; unknown bytes are skipped up to the next pack.
    """

    def __init__(self, *, skip_first_group: bool) -> None:
        self._buf = bytearray()
        self._header = True
        self._rtp: RtpToPs | None = None
        self._groups = 0
        self._skip = skip_first_group
        self._keyframe = False
        self.codec = _DEFAULT_CODEC
        # For the debug log: what the stream carried, whether or not it played.
        self.groups = 0
        self.stream_ids: set[int] = set()
        # Per stream id: packets, bytes, and for video the kinds of NAL unit that
        # opened a packet (which says whether that track carries keyframes).
        self.stats: dict[int, list[int]] = {}
        self.nals: dict[int, set[int]] = {}

    def feed(self, data: bytes) -> list[tuple[bytes, bool]]:
        """Add ``data``; return the packs it completed, each with whether it is a keyframe.

        Some cameras (the EP4) send RTP instead of MPEG-PS, one packet per call;
        that is turned into MPEG-PS first, so everything after reads it the same.
        """
        if self._header and self._rtp is None and RtpToPs.starts(data):
            self._rtp = RtpToPs()
            self._header = False
        if self._rtp is not None:
            data = self._rtp.feed(data)
        self._buf += data
        if self._header:
            if len(self._buf) < 4:
                return []
            if self._buf[:4] == b"IMKH":
                if len(self._buf) < _IMKH_HEADER:
                    return []
                del self._buf[:_IMKH_HEADER]
            self._header = False
        ps = self._buf
        done: list[tuple[bytes, bool]] = []
        i, start = 0, None
        while i + 6 <= len(ps):
            if ps[i : i + 3] != b"\x00\x00\x01":
                i = ps.find(b"\x00\x00\x01\xba", i + 1)
                if i < 0:
                    i = max(len(ps) - 3, 0)
                    start = None
                    break
                start = None
                continue
            stream_id = ps[i + 3]
            self.stream_ids.add(stream_id)
            if stream_id == 0xBA:  # pack header: fixed 14 bytes plus stuffing
                if i + 14 > len(ps) or i + 14 + (ps[i + 13] & 7) > len(ps):
                    break
                if start is not None:
                    self._complete(bytes(ps[start:i]), done)
                start, self._keyframe = i, False
                i += 14 + (ps[i + 13] & 7)
                continue
            end = i + 6 + int.from_bytes(ps[i + 4 : i + 6], "big")
            if end > len(ps):
                break
            if stream_id == 0xBC:
                self.codec = _psm_video_codec(bytes(ps[i + 6 : end])) or self.codec
                self._keyframe = True
            i = end
        # Keep the unfinished pack (or the unparsed tail) for the next call.
        del ps[: start if start is not None else i]
        return done

    def summary(self) -> str:
        """What each stream id carried so far, for the debug log."""
        text = "; ".join(
            f"{sid:02x}: {packets} packets, {size} bytes"
            + (f", NAL types {sorted(self.nals[sid])}" if sid in self.nals else "")
            for sid, (packets, size) in sorted(self.stats.items())
        )
        return f"{self._rtp.summary()}; {text}" if self._rtp is not None else text

    def _count(self, pack: bytes) -> None:
        for sid, start, end in _packets(pack):
            entry = self.stats.setdefault(sid, [0, 0])
            entry[0] += 1
            entry[1] += end - start
            if _is_video(sid) and start + 9 <= end:
                body = pack[start + 9 + pack[start + 8] : end]
                for code in (b"\x00\x00\x00\x01", b"\x00\x00\x01"):
                    if body.startswith(code) and len(body) > len(code):
                        nal = body[len(code)]
                        kind = nal & 0x1F if self.codec == "h264" else (nal >> 1) & 0x3F
                        self.nals.setdefault(sid, set()).add(kind)
                        break

    def _complete(self, pack: bytes, done: list[tuple[bytes, bool]]) -> None:
        self._count(pack)
        if self._keyframe:
            self._groups += 1
            self.groups = self._groups
        if self._skip and self._groups < 2:
            return
        done.append((pack, self._keyframe))


_RTP_SOURCE = b"\x55\x66\x77\x88"  # the fixed RTP source id these cameras send
_RTP_VIDEO_PT = 96  # used when the stream doesn't say which payload type is video
_PES_CHUNK = 60_000
_PTS_START = 90_000  # one second in, so the first picture never sits at zero


class RtpToPs:
    """Turns RTP video (H.265 or H.264, RFC 7798 / 6184) into MPEG-PS, one pack per picture.

    The first packet's header extension can carry a stream descriptor (0x45:
    stream type, payload type), which says which payload type is the video and
    its codec. Audio and the other payload types are dropped.
    """

    def __init__(self) -> None:
        self.video_pt: int | None = None
        self.codec: str | None = None
        self.payload_types: dict[int, int] = {}
        self.dropped = 0
        self._nals: list[bytes] = []
        self._ts: int | None = None
        self._t0: int | None = None
        self._fu: bytearray | None = None
        self._seq: int | None = None

    @staticmethod
    def starts(data: bytes) -> bool:
        """Whether ``data`` is the first packet of such a stream."""
        return len(data) >= 12 and data[0] >> 6 == 2 and data[8:12] == _RTP_SOURCE

    def summary(self) -> str:
        """What the RTP carried, for the debug log."""
        types = ", ".join(f"{pt}: {n}" for pt, n in sorted(self.payload_types.items()))
        return (
            f"RTP payload types {{{types}}}, video {self.video_pt} {self.codec}, "
            f"{self.dropped} fragments dropped"
        )

    def feed(self, data: bytes) -> bytes:
        """Take one RTP packet; return the MPEG-PS of any picture it completed."""
        if len(data) < 12 or data[0] >> 6 != 2:
            return b""
        pt, marker = data[1] & 0x7F, bool(data[1] & 0x80)
        seq = int.from_bytes(data[2:4], "big")
        ts = int.from_bytes(data[4:8], "big")
        offset = 12 + (data[0] & 0x0F) * 4
        if data[0] & 0x10 and len(data) >= offset + 4:
            ext_end = offset + 4 + int.from_bytes(data[offset + 2 : offset + 4], "big") * 4
            self._descriptors(data[offset + 4 : ext_end])
            offset = ext_end
        end = len(data) - (data[-1] if data[0] & 0x20 else 0)
        payload = data[offset:end]
        self.payload_types[pt] = self.payload_types.get(pt, 0) + 1
        if pt != (self.video_pt if self.video_pt is not None else _RTP_VIDEO_PT) or not payload:
            return b""
        if self.codec is None:
            self.codec = _guess_codec(payload)
            if self.codec is None:  # nothing to decode before the first keyframe anyway
                return b""
        if self._seq is not None and seq != (self._seq + 1) & 0xFFFF and self._fu is not None:
            self._fu = None
            self.dropped += 1
        self._seq = seq
        out = b""
        if self._ts is not None and ts != self._ts and self._nals:
            out = self._flush()
        self._ts = ts
        self._nals += self._depacketize(payload)
        if marker and self._nals:
            out += self._flush()
        return out

    def _descriptors(self, ext: bytes) -> None:
        i = 0
        while i + 4 <= len(ext):
            tag, length = ext[i], ext[i + 1]
            if tag == 0x45 and length >= 2 and ext[i + 2] in _CODECS:
                self.codec = _CODECS[ext[i + 2]]
                self.video_pt = ext[i + 3] & 0x7F
            i += 2 + length

    def _depacketize(self, p: bytes) -> list[bytes]:
        hevc = self.codec == "hevc"
        head = 2 if hevc else 1
        kind = (p[0] >> 1) & 0x3F if hevc else p[0] & 0x1F
        if kind == (48 if hevc else 24):  # aggregation: several NAL units, each sized
            units, i = [], head
            while i + 2 <= len(p):
                size = int.from_bytes(p[i : i + 2], "big")
                units.append(p[i + 2 : i + 2 + size])
                i += 2 + size
            return [u for u in units if u]
        if kind != (49 if hevc else 28):  # a whole NAL unit
            return [p]
        if len(p) <= head:  # a fragment too short to carry its header
            self.dropped += 1
            return []
        fu = p[head]
        if fu & 0x80:  # first fragment: rebuild the NAL header it replaced
            nal_type = fu & 0x3F if hevc else fu & 0x1F
            first = (
                bytes(((p[0] & 0x81) | (nal_type << 1), p[1]))
                if hevc
                else bytes(((p[0] & 0xE0) | nal_type,))
            )
            self._fu = bytearray(first)
        elif self._fu is None:
            self.dropped += 1
            return []
        self._fu += p[head + 1 :]
        if not fu & 0x40:
            return []
        nal, self._fu = bytes(self._fu), None
        return [nal]

    def _flush(self) -> bytes:
        nals, self._nals = self._nals, []
        assert self._ts is not None
        if self._t0 is None:
            self._t0 = self._ts
        # ponytail: 32-bit RTP clock wraps after ~13 h at 90 kHz; live streams are minutes.
        pts = _PTS_START + ((self._ts - self._t0) & 0xFFFFFFFF)
        types = {(n[0] >> 1) & 0x3F if self.codec == "hevc" else n[0] & 0x1F for n in nals}
        key = bool(types & ({16, 17, 18, 19, 20, 21, 32} if self.codec == "hevc" else {5, 7}))
        out = bytearray(_pack_header(pts))
        if key:
            stream_type = 0x24 if self.codec == "hevc" else 0x1B
            body = b"\xe0\xff\x00\x00\x00\x04" + bytes((stream_type, 0xE0, 0, 0))
            out += b"\x00\x00\x01\xbc" + (len(body) + 4).to_bytes(2, "big") + body + bytes(4)
        # Each NAL unit opens its own PES packet: pyezvizapi finds the units to
        # decrypt one PES payload at a time, so a start code cut in two is missed.
        first = True
        for n in nals:
            unit = b"\x00\x00\x00\x01" + n
            for i in range(0, len(unit), _PES_CHUNK):
                out += _pes_packet(unit[i : i + _PES_CHUNK], pts if first else None)
                first = False
        return bytes(out)


def _guess_codec(p: bytes) -> str | None:
    """The codec of an RTP payload that holds a parameter set or a keyframe NAL unit.

    It looks inside aggregation packets and first fragments too. Other payloads
    can read as either codec, so they give no answer.
    """
    if len(p) > 2 and p[1] == 0x01:  # H.265: layer 0, temporal id 1
        t = (p[0] >> 1) & 0x3F
        if t == 48 and len(p) > 4:
            t = (p[4] >> 1) & 0x3F
        elif t == 49 and p[2] & 0x80:
            t = p[2] & 0x3F
        if 16 <= t <= 21 or 32 <= t <= 34:
            return "hevc"
    if p[0] & 0x80:  # forbidden bit
        return None
    t = p[0] & 0x1F
    if t == 24 and len(p) > 3:
        t = p[3] & 0x1F
    elif t == 28 and len(p) > 1 and p[1] & 0x80:
        t = p[1] & 0x1F
    return "h264" if t in (5, 7) else None


def _pack_header(scr: int) -> bytes:
    """MPEG-2 pack header with ``scr`` (90 kHz), the highest mux rate and no stuffing."""
    return b"\x00\x00\x01\xba" + bytes(
        (
            0x44 | ((scr >> 27) & 0x38) | ((scr >> 28) & 0x03),
            (scr >> 20) & 0xFF,
            ((scr >> 12) & 0xF8) | 0x04 | ((scr >> 13) & 0x03),
            (scr >> 5) & 0xFF,
            ((scr << 3) & 0xF8) | 0x04,
            0x01,
            0xFF,
            0xFF,
            0xFF,
            0xF8,
        )
    )


def _pes_packet(payload: bytes, pts: int | None) -> bytes:
    """Video PES packet (0xE0), with a PTS when given."""
    if pts is None:
        header = b"\x80\x00\x00"
    else:
        header = b"\x80\x80\x05" + bytes(
            (
                0x21 | ((pts >> 29) & 0x0E),
                (pts >> 22) & 0xFF,
                ((pts >> 14) & 0xFE) | 1,
                (pts >> 7) & 0xFF,
                ((pts << 1) & 0xFE) | 1,
            )
        )
    return b"\x00\x00\x01\xe0" + (len(header) + len(payload)).to_bytes(2, "big") + header + payload


def _is_video(stream_id: int) -> bool:
    return 0xE0 <= stream_id <= 0xEF


def _packets(pack: bytes) -> Iterator[tuple[int, int, int]]:
    """The packets of one pack, after its header: (stream id, start, end)."""
    if len(pack) < 14:
        return
    i = 14 + (pack[13] & 7)
    while i + 6 <= len(pack) and pack[i : i + 3] == b"\x00\x00\x01":
        end = min(i + 6 + int.from_bytes(pack[i + 4 : i + 6], "big"), len(pack))
        yield pack[i + 3], i, end
        i = end


def keep_video(pack: bytes, stream_id: int) -> bytes:
    """``pack`` without the video packets of any stream but ``stream_id``.

    A camera with two lenses can send both in one stream, as two video streams
    (0xE0 and 0xE1); a player then shows whichever it meets first.
    """
    out = bytearray(pack)
    for sid, start, end in reversed(list(_packets(pack))):
        if _is_video(sid) and sid != stream_id:
            del out[start:end]
    return bytes(out)


def decrypt_packs(packs: list[bytes], code: str | None, codec: str) -> list[bytes]:
    """Decrypt whole packs in one go, then cut them back apart. Blocking (CPU-bound).

    Decryption keeps every byte in place, and no NAL unit spans two packs, so
    this equals decrypting each pack on its own.
    """
    if not code:
        return packs
    clear = _decrypt(b"".join(packs), code, codec)
    out, pos = [], 0
    for pack in packs:
        out.append(clear[pos : pos + len(pack)])
        pos += len(pack)
    return out


async def async_ps_to_jpeg(ps: bytes, ffmpeg_bin: str) -> bytes:
    """Decode the first frame of an MPEG-PS stream into a JPEG.

    ffmpeg is used instead of a Python codec binding so the integration carries
    no native-codec dependency of its own; Home Assistant always provides the
    binary through its ffmpeg integration.
    """
    jpeg, err = await _ffmpeg(
        ffmpeg_bin, ps, "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "pipe:1"
    )
    if not jpeg.startswith(b"\xff\xd8"):
        raise EzvizCloudDecodeError(f"Could not decode a keyframe: {err or 'no frame decoded'}")
    return jpeg


async def async_ps_to_mp4(ps: bytes, codec: str, ffmpeg_bin: str) -> bytes:
    """Repackage the video of an MPEG-PS stream as fragmented MP4, without re-encoding."""
    # Safari only plays H.265 in MP4 under the hvc1 tag; ffmpeg defaults to hev1.
    tag = ("-tag:v", "hvc1") if codec == "hevc" else ()
    mp4, err = await _ffmpeg(
        ffmpeg_bin,
        ps,
        "-c",
        "copy",
        *tag,
        "-f",
        "mp4",
        "-movflags",
        "frag_keyframe+empty_moov+default_base_moof",
        "pipe:1",
    )
    if not mp4:
        raise EzvizCloudError(f"Could not package the video: {err or 'no video'}")
    return mp4


async def _ffmpeg(ffmpeg_bin: str, ps: bytes, *output: str) -> tuple[bytes, str]:
    """Run ffmpeg on an MPEG-PS fed through stdin; returns stdout and stderr."""
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "mpeg",
        "-i",
        "pipe:0",
        "-map",
        "0:v:0",
        *output,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(_FFMPEG_TIMEOUT):
            out, err = await proc.communicate(ps)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise EzvizCloudError("ffmpeg did not finish in time") from exc
    return out, err.decode(errors="replace").strip()


def _decrypt(ps: bytes, code: str, codec: str) -> bytes:
    """Decrypt the encrypted NAL bodies with the verification code (pyezvizapi).

    The NAL header stays in the clear: two bytes in H.265, one in H.264.
    """
    # Top-level name: 1.x keeps it in cloud_stream/stream, 2.x in streaming.media
    from pyezvizapi import decrypt_hikvision_ps_video  # type: ignore[attr-defined]

    return decrypt_hikvision_ps_video(ps, code, nalu_header_size=1 if codec == "h264" else 2)


def _psm_video_codec(psm: bytes) -> str | None:
    """The codec of the video stream (0xE0) listed in a program stream map."""
    j = 4 + int.from_bytes(psm[2:4], "big")  # skip the program stream info
    end = j + 2 + int.from_bytes(psm[j : j + 2], "big")
    j += 2
    while j + 4 <= min(end, len(psm)):
        stream_type, stream_id = psm[j], psm[j + 1]
        if stream_id == 0xE0:
            return _CODECS.get(stream_type)
        j += 4 + int.from_bytes(psm[j + 2 : j + 4], "big")
    return None
