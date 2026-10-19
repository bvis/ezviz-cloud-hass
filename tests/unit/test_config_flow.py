"""Config and options flows: credential validation, error mapping, stored and checked codes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.ezviz_cloud.api import Camera, EzvizCloudAuthError, EzvizCloudError
from custom_components.ezviz_cloud.config_flow import EzvizCloudConfigFlow, EzvizCloudOptionsFlow
from custom_components.ezviz_cloud.snapshot import EzvizCloudDecodeError

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
    entry.runtime_data.manager.async_get_token = AsyncMock(return_value=MagicMock(token="at.x"))
    entry.runtime_data.manager.api.async_get_cameras = AsyncMock(
        return_value=cameras, side_effect=exc
    )
    entry.runtime_data.cameras = [Camera("BK1", 1, "Door", True)]
    entry.runtime_data.streams = {}
    flow = EzvizCloudOptionsFlow()
    flow.__dict__["_entry"] = entry
    flow.hass = MagicMock()
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
    flow = _options_flow(cameras=cams)
    result = await flow.async_step_codes()
    # BK2 has no entities yet: the account reloads to add it.
    flow.hass.config_entries.async_schedule_reload.assert_called_once()
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
    result = await _options_flow(**kwargs).async_step_codes()
    assert result["type"] == "abort"
    assert result["reason"] == reason


async def test_options_stores_code_uppercased() -> None:
    result = await _options_flow().async_step_codes({"serial": "BK2", "code": " abcdef "})
    assert result["type"] == "create_entry"
    assert result["data"] == {"codes": {"BK1": "OLDOLD", "BK2": "ABCDEF"}}


def _check(flow: EzvizCloudOptionsFlow, grab: AsyncMock, active: bool = False):  # type: ignore[no-untyped-def]
    """Give BK1 an idle (or busy) stream and patch the keyframe grab."""
    flow.config_entry.runtime_data.streams = {"BK1": MagicMock(active=active)}
    flow.config_entry.runtime_data.manager = MagicMock()
    flow.config_entry.runtime_data.manager.async_get_token = AsyncMock(
        return_value=MagicMock(token="at.x")
    )
    flow.config_entry.runtime_data.manager.api.async_get_cameras = AsyncMock(
        return_value=[Camera("BK1", 1, "Door", True)]
    )
    probe = MagicMock(async_close=AsyncMock())
    return (
        patch("custom_components.ezviz_cloud.config_flow.async_grab_jpeg", grab),
        patch("custom_components.ezviz_cloud.config_flow.LiveStream", return_value=probe),
        probe,
    )


async def test_options_checks_the_code_against_the_video() -> None:
    flow = _options_flow()
    p_grab, p_stream, probe = _check(flow, AsyncMock(return_value=b"\xff\xd8"))
    with p_grab as grab, p_stream as stream_cls:
        result = await flow.async_step_codes({"serial": "BK1", "code": "newcod"})
    assert result["type"] == "create_entry"
    assert result["data"]["codes"]["BK1"] == "NEWCOD"
    # The probe plays the camera with the new code, and is closed afterwards.
    assert stream_cls.call_args.args[3]() == "NEWCOD"
    grab.assert_awaited_once_with(flow.hass, probe)
    probe.async_close.assert_awaited_once()


async def test_options_rejects_a_code_that_does_not_decode() -> None:
    flow = _options_flow()
    p_grab, p_stream, probe = _check(flow, AsyncMock(side_effect=EzvizCloudDecodeError("x")))
    with p_grab, p_stream:
        result = await flow.async_step_codes({"serial": "BK1", "code": "WRONG1"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_code"}
    assert result["data_schema"].schema["serial"].config["options"][0]["value"] == "BK1"
    probe.async_close.assert_awaited_once()


async def test_options_saves_unchecked_when_the_camera_does_not_answer() -> None:
    flow = _options_flow()
    p_grab, p_stream, _ = _check(flow, AsyncMock(side_effect=EzvizCloudError("asleep")))
    with p_grab, p_stream:
        result = await flow.async_step_codes({"serial": "BK1", "code": "NEWCOD"})
    assert result["type"] == "create_entry"


@pytest.mark.parametrize("state", [ConfigEntryState.LOADED, ConfigEntryState.NOT_LOADED])
async def test_options_skips_the_check_while_streaming_or_not_loaded(
    state: ConfigEntryState,
) -> None:
    flow = _options_flow(state=state)
    grab = AsyncMock()
    p_grab, p_stream, _ = _check(flow, grab, active=True)
    with p_grab, p_stream:
        result = await flow.async_step_codes({"serial": "BK1", "code": "NEWCOD"})
    assert result["type"] == "create_entry"
    grab.assert_not_awaited()


async def test_options_empty_code_removes_it() -> None:
    result = await _options_flow().async_step_codes({"serial": "BK1"})
    assert result["data"] == {"codes": {}}


async def test_options_menu() -> None:
    result = await _options_flow().async_step_init()
    assert result["type"] == "menu"
    assert result["menu_options"] == ["codes", "recordings"]


async def test_recordings_step_shows_current_values() -> None:
    flow = _options_flow()
    flow.config_entry.options["retention_days"] = 7
    result = await flow.async_step_recordings()
    assert result["type"] == "form"
    defaults = {str(k): k.default() for k in result["data_schema"].schema}
    assert defaults == {"retention_days": 7, "max_per_camera": 100}


async def test_recordings_step_keeps_codes() -> None:
    result = await _options_flow().async_step_recordings(
        {"retention_days": 30.0, "max_per_camera": 0.0}
    )
    assert result["type"] == "create_entry"
    assert result["data"] == {"codes": {"BK1": "OLDOLD"}, "retention_days": 30, "max_per_camera": 0}
