"""Server-side still capture: play the live stream, decode one keyframe to JPEG.

The card decrypts and plays video in the browser; this does the minimum needed
for a single photo without a browser. It plays the same ``ezopen`` live stream
(its URL comes from ``EzvizCloudApi.async_live_url``), keeps the first
keyframe, decrypts the NAL bodies with ``pyezvizapi`` (the verification code is
the AES key) and decodes exactly one frame.

Only the keyframe is used, which is the part that decrypts cleanly; the inter
frames are left for a future full-video capture. Requests to EZVIZ per call:
one ``live/url/ezopen`` request plus the live WebSocket, the same as opening
the card once. Nothing is sent while idle.
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
# MPEG-PS stream types in the program stream map, mapped to ffmpeg demuxers.
_CODECS = {0x1B: "h264", 0x24: "hevc"}
_DEFAULT_CODEC = "hevc"


async def async_capture_ps(
    session: aiohttp.ClientSession,
    stream_url: str,
    *,
    wake_timeout: float = 20.0,
    capture_seconds: float = 4.0,
    max_bytes: int = 400_000,
) -> bytes:
    """Play the live stream and return the first few seconds of raw MPEG-PS.

    Waits up to ``wake_timeout`` for the first video byte (the camera may be
    asleep), then keeps ``capture_seconds`` worth, capped at ``max_bytes``.
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


def decrypt_and_demux(ps: bytes, code: str | None) -> tuple[bytes, str]:
    """Decrypt the MPEG-PS and return its Annex B video and codec. Blocking (CPU-bound)."""
    clear = _decrypt(ps, code) if code else ps
    return _demux_ps(clear)


async def async_annexb_to_jpeg(annexb: bytes, codec: str, ffmpeg_bin: str) -> bytes:
    """Decode the first keyframe of an Annex B stream (``h264``/``hevc``) into a JPEG.

    ffmpeg is used instead of a Python codec binding so the integration carries
    no native-codec dependency of its own; Home Assistant always provides the
    binary through its ffmpeg integration.
    """
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        codec,
        "-i",
        "pipe:0",
        "-frames:v",
        "1",
        "-f",
        "image2",
        "-c:v",
        "mjpeg",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(_FFMPEG_TIMEOUT):
            jpeg, err = await proc.communicate(annexb)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise EzvizCloudError("ffmpeg did not decode a keyframe in time") from exc
    if not jpeg.startswith(b"\xff\xd8"):
        detail = err.decode(errors="replace").strip() or "no frame decoded"
        raise EzvizCloudError(f"Could not decode a keyframe: {detail}")
    return jpeg


def _decrypt(ps: bytes, code: str) -> bytes:
    """Decrypt the encrypted NAL bodies with the verification code (pyezvizapi)."""
    from pyezvizapi.cloud_stream import decrypt_hikvision_ps_video  # type: ignore[attr-defined]

    return decrypt_hikvision_ps_video(ps, code)


def _demux_ps(ps: bytes) -> tuple[bytes, str]:
    """Pull the Annex B video and its codec out of the MPEG-PS the camera sends.

    The video PES payloads already carry Annex B start codes, so concatenating
    them yields a decodable elementary stream. The codec comes from the program
    stream map; without one, HEVC is assumed.
    """
    if ps[:4] == b"IMKH":
        ps = ps[_IMKH_HEADER:]
    out = bytearray()
    codec = _DEFAULT_CODEC
    i, n = 0, len(ps)
    while i + 6 <= n:
        if ps[i : i + 3] != b"\x00\x00\x01":
            nxt = ps.find(b"\x00\x00\x01", i + 1)
            if nxt < 0:
                break
            i = nxt
            continue
        stream_id = ps[i + 3]
        if stream_id == 0xBA:  # pack header: fixed 14 bytes plus stuffing
            if i + 14 > n:  # the capture can cut a pack header short
                break
            i += 14 + (ps[i + 13] & 7)
            continue
        length = int.from_bytes(ps[i + 4 : i + 6], "big")
        body = ps[i + 6 : i + 6 + length]
        if stream_id == 0xE0 and len(body) >= 3:  # video PES: skip its header
            out += body[3 + body[2] :]
        elif stream_id == 0xBC:
            codec = _psm_video_codec(body) or codec
        i += 6 + length
    return bytes(out), codec


def _psm_video_codec(psm: bytes) -> str | None:
    """The ffmpeg demuxer for the video stream (0xE0) listed in a program stream map."""
    j = 4 + int.from_bytes(psm[2:4], "big")  # skip the program stream info
    end = j + 2 + int.from_bytes(psm[j : j + 2], "big")
    j += 2
    while j + 4 <= min(end, len(psm)):
        stream_type, stream_id = psm[j], psm[j + 1]
        if stream_id == 0xE0:
            return _CODECS.get(stream_type)
        j += 4 + int.from_bytes(psm[j + 2 : j + 4], "big")
    return None
