"""Minimal client for the EZVIZ Open Platform token endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

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


class EzvizCloudApi:
    """Fetches access tokens for one appKey from one region."""

    def __init__(
        self, session: aiohttp.ClientSession, domain: str, app_key: str, app_secret: str
    ) -> None:
        self._session = session
        self.domain = domain
        self._app_key = app_key
        self._app_secret = app_secret

    async def async_get_token(self) -> AccessToken:
        """Request an access token. The platform returns the current one until it expires."""
        try:
            async with self._session.post(
                f"{self.domain}/api/lapp/token/get",
                data={"appKey": self._app_key, "appSecret": self._app_secret},
                timeout=_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                body = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EzvizCloudError(f"Cannot reach {self.domain}: {err}") from err

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
