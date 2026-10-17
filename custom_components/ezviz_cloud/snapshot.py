"""Server-side capture: play the live stream, decrypt it, hand it to ffmpeg.

The card decrypts and plays video in the browser; this does the same without a
browser, for the photo and clip buttons. It plays the same ``ezopen`` live
stream (its URL comes from ``EzvizCloudApi.async_live_url``), decrypts the NAL
bodies with ``pyezvizapi`` (the verification code is the AES key) and lets
ffmpeg read the MPEG-PS: one frame to JPEG for a photo, a stream copy to MP4
for a clip.

The stream opens with a group of pictures that is already in the clear and
carries no on-screen clock: that one is skipped, so photos and clips start at
the first live, encrypted keyframe. Requests to EZVIZ per call: one
``live/url/ezopen`` request plus the live WebSocket, the same as opening the
card once. Nothing is sent while idle.
"""

from __future__ import annotations

import asyncio
import json
import logging

import aiohttp

from .api import EzvizCloudError

_LOGGER = logging.getLogger(__name__)

# The player handshake: protocol 0.1, no cipher suite (the NAL bodies carry
# their own AES, keyed by the verification code).
_WS_QUERY = "?version=0.1&cipherSuites=0"
_FFMPEG_TIMEOUT = 15
_IMKH_HEADER = 40  # EZVIZ prefixes the MPEG-PS stream with a 40-byte "IMKH" header.
# MPEG-PS stream types in the program stream map.
_CODECS = {0x1B: "h264", 0x24: "hevc"}
_DEFAULT_CODEC = "hevc"


async def async_capture_ps(
    session: aiohttp.ClientSession,
    stream_url: str,
    *,
    wake_timeout: float = 20.0,
    capture_seconds: float = 7.0,
    max_bytes: int = 400_000,
) -> bytes:
    """Play the live stream and return the first few seconds of raw MPEG-PS.

    Waits up to ``wake_timeout`` for the first video byte (the camera may be
    asleep), then keeps ``capture_seconds`` worth, capped at ``max_bytes``. The
    default is enough to get past the clear first group of pictures (about 3 s)
    to a live keyframe.
    """
    host = stream_url.split("?")[0].replace("/live", "")
    play_param = "/live?" + stream_url.split("?", 1)[1]
    loop = asyncio.get_running_loop()
    buffer = bytearray()
    started: float | None = None
    try:
        async with session.ws_connect(host + _WS_QUERY, max_msg_size=0) as ws:
            sent = False
            deadline = loop.time() + wake_timeout
            while True:
                limit = (started + capture_seconds) if started is not None else deadline
                remaining = limit - loop.time()
                if remaining <= 0:
                    break
                try:
                    msg = await ws.receive(timeout=remaining)
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
                    if started is None:
                        started = loop.time()
                    buffer += msg.data
                    if len(buffer) >= max_bytes:
                        break
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
    except aiohttp.ClientError as err:
        raise EzvizCloudError(f"Live stream failed: {err}") from err
    if not buffer:
        raise EzvizCloudError("No video received; the camera may be asleep")
    return bytes(buffer)


def decrypt_ps(ps: bytes, code: str | None) -> tuple[bytes, str]:
    """Drop the clear start of the stream, decrypt the rest; returns it and its codec.

    Blocking (CPU-bound). pyezvizapi only recognises the packets once the IMKH
    header is gone.
    """
    if ps[:4] == b"IMKH":
        ps = ps[_IMKH_HEADER:]
    start, codec = _scan(ps)
    if not code:
        return ps, codec
    if start is None:
        raise EzvizCloudError("The stream ended before its first live keyframe")
    return _decrypt(ps[start:], code), codec


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
        raise EzvizCloudError(f"Could not decode a keyframe: {err or 'no frame decoded'}")
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


def _decrypt(ps: bytes, code: str) -> bytes:
    """Decrypt the encrypted NAL bodies with the verification code (pyezvizapi)."""
    from pyezvizapi.cloud_stream import decrypt_hikvision_ps_video  # type: ignore[attr-defined]

    return decrypt_hikvision_ps_video(ps, code)


def _scan(ps: bytes) -> tuple[int | None, str]:
    """Offset of the pack that opens the second group of pictures, and the video codec.

    Each group starts with a pack carrying a program stream map (0xBC), which
    also names the codec; without one, HEVC is assumed. Packet lengths are
    trusted, so payload bytes are never mistaken for headers.
    """
    i, pack, maps, codec = 0, 0, 0, _DEFAULT_CODEC
    while i + 6 <= len(ps) and ps[i : i + 3] == b"\x00\x00\x01":
        stream_id = ps[i + 3]
        if stream_id == 0xBA:  # pack header: fixed 14 bytes plus stuffing
            if i + 14 > len(ps):
                break
            pack = i
            i += 14 + (ps[i + 13] & 7)
            continue
        length = int.from_bytes(ps[i + 4 : i + 6], "big")
        if stream_id == 0xBC:
            codec = _psm_video_codec(ps[i + 6 : i + 6 + length]) or codec
            maps += 1
            if maps == 2:
                return pack, codec
        i += 6 + length
    return None, codec


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
