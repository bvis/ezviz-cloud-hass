"""Keeps one valid access token per config entry, renewing it on demand."""

from __future__ import annotations

import asyncio

from homeassistant.util import dt as dt_util

from .api import AccessToken, EzvizCloudApi
from .const import TOKEN_RENEW_MARGIN


class TokenManager:
    """Hands out a cached token and only calls the platform when it is close to expiry.

    Tokens are fetched lazily, when a card starts a stream, so an idle install
    makes no API calls at all after setup.
    """

    def __init__(self, api: EzvizCloudApi) -> None:
        self.api = api
        self._token: AccessToken | None = None
        self._lock = asyncio.Lock()

    @property
    def expires_at(self) -> str | None:
        """Expiry of the cached token, for diagnostics."""
        return self._token.expires_at.isoformat() if self._token else None

    async def async_get_token(self) -> AccessToken:
        """Return a token valid for at least TOKEN_RENEW_MARGIN."""
        async with self._lock:
            if (
                self._token is None
                or self._token.expires_at - dt_util.utcnow() < TOKEN_RENEW_MARGIN
            ):
                self._token = await self.api.async_get_token()
            return self._token
