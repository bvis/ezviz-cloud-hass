"""TokenManager: one API call per token lifetime."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.util import dt as dt_util

from custom_components.ezviz_cloud.api import AccessToken
from custom_components.ezviz_cloud.token import TokenManager


def _manager(*tokens: AccessToken) -> tuple[TokenManager, MagicMock]:
    api = MagicMock()
    api.async_get_token = AsyncMock(side_effect=list(tokens))
    return TokenManager(api), api


async def test_reuses_token_while_far_from_expiry() -> None:
    fresh = AccessToken("at.1", dt_util.utcnow() + timedelta(days=6))
    manager, api = _manager(fresh)
    assert manager.expires_at is None
    assert (await manager.async_get_token()).token == "at.1"
    assert (await manager.async_get_token()).token == "at.1"
    assert api.async_get_token.await_count == 1
    assert manager.expires_at == fresh.expires_at.isoformat()


async def test_renews_when_less_than_a_day_is_left() -> None:
    now = dt_util.utcnow()
    manager, api = _manager(
        AccessToken("at.1", now + timedelta(days=1, hours=1)),
        AccessToken("at.2", now + timedelta(days=8)),
    )
    await manager.async_get_token()
    with patch(
        "custom_components.ezviz_cloud.token.dt_util.utcnow",
        return_value=now + timedelta(hours=2),
    ):
        assert (await manager.async_get_token()).token == "at.2"
    assert api.async_get_token.await_count == 2
