"""Server-side still capture: open the live stream, decode one keyframe to JPEG.

The card decrypts and plays video in the browser; this does the minimum needed
for a single photo without a browser. It opens the same ``ezopen`` live stream,
keeps the first keyframe, decrypts the NAL bodies with ``pyezvizapi`` (the
verification code is the AES key) and decodes exactly one frame.

Only the keyframe is used, which is the part that decrypts cleanly; the inter
frames are left for a future full-video capture. Requests to EZVIZ per call:
one ``live/address/get`` plus the live WebSocket, the same as opening the card
once. Nothing is sent while idle.
"""

from __future__ import annotations

import asyncio
import json
import logging

import aiohttp

from .api import EzvizCloudError

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=15)
# The player handshake: protocol 0.1, no cipher suite (the NAL bodies carry
# their own AES, keyed by the verification code).
_WS_QUERY = "?version=0.1&cipherSuites=0"
_IMKH_HEADER = 40  # EZVIZ prefixes the MPEG-PS stream with a 40-byte "IMKH" header.


async def async_capture_ps(
    session: aiohttp.ClientSession,
    api_domain: str,
    token: str,
    serial: str,
    channel: int,
    code: str | None,
    *,
    wake_timeout: float = 20.0,
    capture_seconds: float = 4.0,
    max_bytes: int = 400_000,
) -> bytes:
    """Open the live stream and return the first few seconds of raw MPEG-PS.

    Waits up to ``wake_timeout`` for the first video byte (the camera may be
    asleep), then keeps ``capture_seconds`` worth, capped at ``max_bytes``.
    """
    url = await _resolve_stream(session, api_domain, token, serial, channel, code)
    return await _collect_keyframe(session, url, wake_timeout, capture_seconds, max_bytes)


async def _resolve_stream(
    session: aiohttp.ClientSession,
    api_domain: str,
    token: str,
    serial: str,
    channel: int,
    code: str | None,
) -> str:
    """Ask the platform for the live WebSocket URL, with its session token appended."""
    ezopen = f"ezopen://{code + '@' if code else ''}open.ezviz.com/{serial}/{channel}.live"
    form = {
        "accessToken": token,
        "ezopen": ezopen,
        "isFlv": "false",
        "isHttp": "false",
        "userAgent": "HomeAssistant",
    }
    try:
        async with session.post(
            f"{api_domain}/api/lapp/live/url/ezopen", data=form, timeout=_TIMEOUT
        ) as resp:
            resp.raise_for_status()
            body = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise EzvizCloudError(f"Cannot reach {api_domain}: {err}") from err
    if str(body.get("code")) != "200" or not (body.get("data") or {}).get("url"):
        raise EzvizCloudError(f"Live URL request failed: {body.get('code')} {body.get('msg')}")
    data = body["data"]
    return f"{data['url']}&ssn={data['token']}&auth=1&biz=4&cln=100"


async def _collect_keyframe(
    session: aiohttp.ClientSession,
    url: str,
    wake_timeout: float,
    capture_seconds: float,
    max_bytes: int,
) -> bytes:
    """Play the stream over the WebSocket and buffer the first burst of video."""
    host = url.split("?")[0].replace("/live", "")
    play_param = "/live?" + url.split("?", 1)[1]
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
                    info = json.loads(msg.data)
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


def decrypt_and_demux(ps: bytes, code: str | None) -> bytes:
    """Decrypt the MPEG-PS and return its Annex B video. Blocking (CPU-bound)."""
    clear = _decrypt(ps, code) if code else ps
    return _demux_ps(clear)


async def async_annexb_to_jpeg(annexb: bytes, ffmpeg_bin: str) -> bytes:
    """Decode the first keyframe of an HEVC Annex B stream into a JPEG, via ffmpeg.

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
        "hevc",
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
    jpeg, err = await proc.communicate(annexb)
    if not jpeg.startswith(b"\xff\xd8"):
        detail = err.decode(errors="replace").strip() or "no frame decoded"
        raise EzvizCloudError(f"Could not decode a keyframe: {detail}")
    return jpeg


def _decrypt(ps: bytes, code: str) -> bytes:
    """Decrypt the encrypted NAL bodies with the verification code (pyezvizapi)."""
    from pyezvizapi.cloud_stream import decrypt_hikvision_ps_video  # type: ignore[attr-defined]

    return decrypt_hikvision_ps_video(ps, code)


def _demux_ps(ps: bytes) -> bytes:
    """Pull the Annex B video out of the MPEG-PS the camera sends.

    The video PES payloads already carry Annex B start codes, so concatenating
    them yields a decodable elementary stream.
    """
    if ps[:4] == b"IMKH":
        ps = ps[_IMKH_HEADER:]
    out = bytearray()
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
            i += 14 + (ps[i + 13] & 7)
            continue
        length = int.from_bytes(ps[i + 4 : i + 6], "big")
        body = ps[i + 6 : i + 6 + length]
        if stream_id == 0xE0 and len(body) >= 3:  # video PES: skip its header
            out += body[3 + body[2] :]
        i += 6 + length
    return bytes(out)
