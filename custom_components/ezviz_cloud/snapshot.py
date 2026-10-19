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
from collections.abc import AsyncIterator

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
    host = stream_url.split("?")[0].replace("/live", "")
    play_param = "/live?" + stream_url.split("?", 1)[1]
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
        self._groups = 0
        self._skip = skip_first_group
        self._keyframe = False
        self.codec = _DEFAULT_CODEC

    def feed(self, data: bytes) -> list[tuple[bytes, bool]]:
        """Add ``data``; return the packs it completed, each with whether it is a keyframe."""
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

    def _complete(self, pack: bytes, done: list[tuple[bytes, bool]]) -> None:
        if self._keyframe:
            self._groups += 1
        if self._skip and self._groups < 2:
            return
        done.append((pack, self._keyframe))


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
    from pyezvizapi.cloud_stream import decrypt_hikvision_ps_video  # type: ignore[attr-defined]

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
