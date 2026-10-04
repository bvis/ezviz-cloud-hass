"""EzvizCloudApi: token parsing and error classification."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.ezviz_cloud.api import (
    EzvizCloudApi,
    EzvizCloudAuthError,
    EzvizCloudError,
)


def _api(body: dict | None = None, exc: Exception | None = None) -> tuple[EzvizCloudApi, MagicMock]:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(side_effect=exc) if exc else MagicMock(return_value=ctx)
    return EzvizCloudApi(session, "https://ieuopen.ezvizlife.com", "key", "secret"), session


async def test_returns_token_and_expiry() -> None:
    api, session = _api(
        {"code": "200", "data": {"accessToken": "at.abc", "expireTime": 1791673050635}}
    )
    token = await api.async_get_token()
    assert token.token == "at.abc"
    assert token.expires_at == datetime.fromtimestamp(1791673050.635, tz=UTC)
    session.post.assert_called_once()
    assert session.post.call_args.args[0] == "https://ieuopen.ezvizlife.com/api/lapp/token/get"
    assert session.post.call_args.kwargs["data"] == {"appKey": "key", "appSecret": "secret"}


@pytest.mark.parametrize("code", ["10005", "10017", "10030"])
async def test_credential_codes_raise_auth_error(code: str) -> None:
    api, _ = _api({"code": code, "msg": "AppKey doesn't exist"})
    with pytest.raises(EzvizCloudAuthError):
        await api.async_get_token()


async def test_other_codes_raise_generic_error() -> None:
    api, _ = _api({"code": "49999", "msg": "Data exception"})
    with pytest.raises(EzvizCloudError) as err:
        await api.async_get_token()
    assert not isinstance(err.value, EzvizCloudAuthError)


async def test_success_without_token_is_an_error() -> None:
    api, _ = _api({"code": "200", "data": None})
    with pytest.raises(EzvizCloudError):
        await api.async_get_token()


@pytest.mark.parametrize("exc", [aiohttp.ClientError("boom"), TimeoutError()])
async def test_network_failures_raise_generic_error(exc: Exception) -> None:
    api, _ = _api(exc=exc)
    with pytest.raises(EzvizCloudError) as err:
        await api.async_get_token()
    assert not isinstance(err.value, EzvizCloudAuthError)
