"""EzvizCloudApi: token parsing and error classification."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.ezviz_cloud.api import (
    Camera,
    EzvizCloudApi,
    EzvizCloudAuthError,
    EzvizCloudError,
)


def _api(
    body: dict | None = None, exc: Exception | None = None, bodies: list[dict] | None = None
) -> tuple[EzvizCloudApi, MagicMock]:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(side_effect=bodies) if bodies else AsyncMock(return_value=body)
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


def _cam(i: int) -> dict:
    return {"deviceSerial": f"BK{i}", "channelNo": 1, "channelName": f"Cam {i}", "isEncrypt": 1}


async def test_lists_cameras_across_pages() -> None:
    api, session = _api(
        bodies=[
            {"code": "200", "data": [_cam(i) for i in range(50)], "page": {"total": 51}},
            {
                "code": "200",
                "data": [{"deviceSerial": "BKX", "isEncrypt": 0}],
                "page": {"total": 51},
            },
        ]
    )
    cameras = await api.async_get_cameras("at.x")
    assert len(cameras) == 51
    assert cameras[0] == Camera("BK0", 1, "Cam 0", True)
    assert cameras[-1] == Camera("BKX", 1, "BKX", False)
    assert [c.kwargs["data"]["pageStart"] for c in session.post.call_args_list] == [0, 1]
    assert session.post.call_args.args[0] == "https://ieuopen.ezvizlife.com/api/lapp/camera/list"


async def test_camera_list_error_code_raises() -> None:
    api, _ = _api({"code": "10002", "msg": "accessToken expired"})
    with pytest.raises(EzvizCloudError):
        await api.async_get_cameras("at.x")


async def test_capture_returns_picture_url() -> None:
    api, session = _api(
        {"code": "200", "data": {"picUrl": "https://pmseu1.ezvizlife.com:8444/x?c=1"}}
    )
    assert await api.async_capture("at.x", "BK1") == "https://pmseu1.ezvizlife.com:8444/x?c=1"
    assert session.post.call_args.args[0] == "https://ieuopen.ezvizlife.com/api/lapp/device/capture"
    assert session.post.call_args.kwargs["data"] == {
        "accessToken": "at.x",
        "deviceSerial": "BK1",
        "channelNo": 1,
    }


async def test_capture_device_timeout_raises() -> None:
    api, _ = _api({"code": "20008", "msg": "Device response timeout"})
    with pytest.raises(EzvizCloudError):
        await api.async_capture("at.x", "BK1")


def _get_api(body: bytes = b"\xff\xd8jpeg", exc: Exception | None = None) -> EzvizCloudApi:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.read = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(side_effect=exc) if exc else MagicMock(return_value=ctx)
    return EzvizCloudApi(session, "https://ieuopen.ezvizlife.com", "key", "secret")


async def test_download_from_ezviz_host() -> None:
    url = "https://pmseu1.ezvizlife.com:8444/p?c=1"
    assert await _get_api().async_download(url) == b"\xff\xd8jpeg"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/p.jpg",
        "https://ezvizlife.com.evil.example/p.jpg",
        "file:///etc/passwd",
    ],
)
async def test_download_rejects_other_hosts(url: str) -> None:
    with pytest.raises(EzvizCloudError):
        await _get_api().async_download(url)


async def test_download_network_failure() -> None:
    with pytest.raises(EzvizCloudError):
        await _get_api(exc=aiohttp.ClientError("boom")).async_download("https://a.ys7.com/p")
