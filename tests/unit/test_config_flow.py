"""Config flow: credential validation and error mapping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ezviz_cloud.api import EzvizCloudAuthError, EzvizCloudError
from custom_components.ezviz_cloud.config_flow import EzvizCloudConfigFlow

USER_INPUT = {"region": "eu", "app_key": " key ", "app_secret": " secret "}


def _flow() -> EzvizCloudConfigFlow:
    flow = EzvizCloudConfigFlow()
    flow.hass = MagicMock()
    flow.async_set_unique_id = AsyncMock()  # type: ignore[method-assign]
    flow._abort_if_unique_id_configured = MagicMock()  # type: ignore[method-assign]
    return flow


async def test_shows_form_first() -> None:
    result = await _flow().async_step_user()
    assert result["type"] == "form"
    assert result["errors"] == {}


async def test_creates_entry_with_trimmed_credentials() -> None:
    flow = _flow()
    with (
        patch("custom_components.ezviz_cloud.config_flow.async_get_clientsession"),
        patch("custom_components.ezviz_cloud.config_flow.EzvizCloudApi") as api_cls,
    ):
        api_cls.return_value.async_get_token = AsyncMock()
        result = await flow.async_step_user(dict(USER_INPUT))
    assert result["type"] == "create_entry"
    assert result["title"] == "EZVIZ Cloud (EU)"
    assert result["data"] == {"region": "eu", "app_key": "key", "app_secret": "secret"}
    assert api_cls.call_args.args[1:] == ("https://ieuopen.ezvizlife.com", "key", "secret")
    flow.async_set_unique_id.assert_awaited_once_with("key")


@pytest.mark.parametrize(
    ("exc", "error"),
    [(EzvizCloudAuthError("bad"), "invalid_auth"), (EzvizCloudError("down"), "cannot_connect")],
)
async def test_maps_errors(exc: Exception, error: str) -> None:
    with (
        patch("custom_components.ezviz_cloud.config_flow.async_get_clientsession"),
        patch("custom_components.ezviz_cloud.config_flow.EzvizCloudApi") as api_cls,
    ):
        api_cls.return_value.async_get_token = AsyncMock(side_effect=exc)
        result = await _flow().async_step_user(dict(USER_INPUT))
    assert result["type"] == "form"
    assert result["errors"] == {"base": error}
