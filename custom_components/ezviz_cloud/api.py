"""Minimal client for the EZVIZ Open Platform: access tokens and the camera list."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiohttp

# Open Platform result codes that mean the appKey/appSecret pair is wrong,
# as opposed to a transient failure worth retrying.
_AUTH_ERROR_CODES = {"10005", "10017", "10030"}
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class EzvizCloudError(Exception):
    """The Open Platform could not be reached or answered with an error."""


class EzvizCloudAuthError(EzvizCloudError):
    """The appKey/appSecret pair was rejected."""


@dataclass(frozen=True)
class AccessToken:
    """An Open Platform access token and the moment it stops working."""

    token: str
    expires_at: datetime


@dataclass(frozen=True)
class Camera:
    """One camera channel of the account."""

    serial: str
    channel: int
    name: str
    encrypted: bool


class EzvizCloudApi:
    """Talks to the Open Platform for one appKey in one region."""

    def __init__(
        self, session: aiohttp.ClientSession, domain: str, app_key: str, app_secret: str
    ) -> None:
        self._session = session
        self.domain = domain
        self._app_key = app_key
        self._app_secret = app_secret

    async def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """POST a form to the platform and return the body, raising on network errors."""
        try:
            async with self._session.post(
                f"{self.domain}{path}", data=data, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                body: dict[str, Any] = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EzvizCloudError(f"Cannot reach {self.domain}: {err}") from err
        return body

    async def async_get_token(self) -> AccessToken:
        """Request an access token. The platform returns the current one until it expires."""
        body = await self._post(
            "/api/lapp/token/get", {"appKey": self._app_key, "appSecret": self._app_secret}
        )
        code = str(body.get("code"))
        if code in _AUTH_ERROR_CODES:
            raise EzvizCloudAuthError(body.get("msg") or code)
        data = body.get("data") or {}
        if code != "200" or not data.get("accessToken"):
            raise EzvizCloudError(f"Token request failed: {code} {body.get('msg')}")
        return AccessToken(
            token=data["accessToken"],
            expires_at=datetime.fromtimestamp(data["expireTime"] / 1000, tz=UTC),
        )

    async def async_get_cameras(self, access_token: str) -> list[Camera]:
        """List every camera channel of the account, following the pages."""
        cameras: list[Camera] = []
        while True:
            body = await self._post(
                "/api/lapp/camera/list",
                {"accessToken": access_token, "pageStart": len(cameras) // 50, "pageSize": 50},
            )
            if str(body.get("code")) != "200":
                raise EzvizCloudError(f"Camera list failed: {body.get('code')} {body.get('msg')}")
            page = body.get("data") or []
            cameras += [
                Camera(
                    serial=c["deviceSerial"],
                    channel=int(c.get("channelNo") or 1),
                    name=c.get("channelName") or c["deviceSerial"],
                    encrypted=bool(c.get("isEncrypt")),
                )
                for c in page
            ]
            if len(page) < 50 or len(cameras) >= int((body.get("page") or {}).get("total") or 0):
                return cameras
