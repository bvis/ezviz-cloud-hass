"""Config and options flows: credential validation, error mapping, stored codes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.ezviz_cloud.api import Camera, EzvizCloudAuthError, EzvizCloudError
from custom_components.ezviz_cloud.config_flow import EzvizCloudConfigFlow, EzvizCloudOptionsFlow

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


def _options_flow(
    state: ConfigEntryState = ConfigEntryState.LOADED,
    cameras: list[Camera] | None = None,
    exc: Exception | None = None,
) -> EzvizCloudOptionsFlow:
    entry = MagicMock(state=state, options={"codes": {"BK1": "OLDOLD"}})
    entry.runtime_data.async_get_token = AsyncMock(return_value=MagicMock(token="at.x"))
    entry.runtime_data.api.async_get_cameras = AsyncMock(return_value=cameras, side_effect=exc)
    flow = EzvizCloudOptionsFlow()
    flow.__dict__["_entry"] = entry
    return flow


@pytest.fixture(autouse=True)
def _entry_property():  # type: ignore[no-untyped-def]
    with patch.object(
        EzvizCloudOptionsFlow, "config_entry", property(lambda self: self.__dict__["_entry"])
    ):
        yield


def test_config_flow_offers_options() -> None:
    assert isinstance(
        EzvizCloudConfigFlow.async_get_options_flow(MagicMock()), EzvizCloudOptionsFlow
    )


async def test_options_form_lists_cameras_once_and_marks_stored_codes() -> None:
    cams = [
        Camera("BK1", 1, "Door", True),
        Camera("BK1", 2, "Door 2", True),
        Camera("BK2", 1, "Yard", False),
    ]
    result = await _options_flow(cameras=cams).async_step_init()
    assert result["type"] == "form"
    options = result["data_schema"].schema["serial"].config["options"]
    assert [(o["value"], o["label"]) for o in options] == [
        ("BK1", "Door (BK1) ✓"),
        ("BK2", "Yard (BK2)"),
    ]


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"state": ConfigEntryState.SETUP_RETRY}, "not_loaded"),
        ({"exc": EzvizCloudError("down")}, "cannot_connect"),
        ({"cameras": []}, "no_cameras"),
    ],
)
async def test_options_aborts(kwargs: dict, reason: str) -> None:
    result = await _options_flow(**kwargs).async_step_init()
    assert result["type"] == "abort"
    assert result["reason"] == reason


async def test_options_stores_code_uppercased() -> None:
    result = await _options_flow().async_step_init({"serial": "BK2", "code": " abcdef "})
    assert result["type"] == "create_entry"
    assert result["data"] == {"codes": {"BK1": "OLDOLD", "BK2": "ABCDEF"}}


async def test_options_empty_code_removes_it() -> None:
    result = await _options_flow().async_step_init({"serial": "BK1"})
    assert result["data"] == {"codes": {}}
