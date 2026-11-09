"""Config and options flows: credential validation, error mapping, stored and checked codes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import AbortFlow

from custom_components.ezviz_cloud.api import Camera, EzvizCloudAuthError, EzvizCloudError
from custom_components.ezviz_cloud.config_flow import EzvizCloudConfigFlow, EzvizCloudOptionsFlow
from custom_components.ezviz_cloud.snapshot import EzvizCloudDecodeError

USER_INPUT = {"region": "eu", "app_key": " key ", "app_secret": " secret "}


def _flow(source: str = "user") -> EzvizCloudConfigFlow:
    flow = EzvizCloudConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": source}

    async def set_unique_id(uid: str) -> None:
        flow.context["unique_id"] = uid

    flow.async_set_unique_id = AsyncMock(side_effect=set_unique_id)  # type: ignore[method-assign]
    flow._abort_if_unique_id_configured = MagicMock()  # type: ignore[method-assign]
    return flow


@pytest.mark.parametrize("step", ["user", "reconfigure"])
async def test_offers_both_sources(step: str) -> None:
    result = await getattr(_flow(step), f"async_step_{step}")()
    assert result["type"] == "menu"
    assert result["menu_options"] == ["open_platform", "app_account"]


async def test_open_platform_shows_form_first() -> None:
    result = await _flow().async_step_open_platform()
    assert result["type"] == "form"
    assert result["errors"] == {}


async def test_creates_entry_with_trimmed_credentials() -> None:
    flow = _flow()
    with (
        patch("custom_components.ezviz_cloud.config_flow.async_get_clientsession"),
        patch("custom_components.ezviz_cloud.config_flow.EzvizCloudApi") as api_cls,
    ):
        api_cls.return_value.async_get_token = AsyncMock()
        result = await flow.async_step_open_platform(dict(USER_INPUT))
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
        result = await _flow().async_step_open_platform(dict(USER_INPUT))
    assert result["type"] == "form"
    assert result["errors"] == {"base": error}


def _entry_flow(
    source: str, data: dict[str, str] | None = None
) -> tuple[EzvizCloudConfigFlow, MagicMock]:
    flow = _flow(source)
    entry = MagicMock(
        entry_id="e1", data=data or {"region": "eu", "app_key": "key", "app_secret": "old"}
    )
    getter = "_get_reauth_entry" if source == "reauth" else "_get_reconfigure_entry"
    setattr(flow, getter, MagicMock(return_value=entry))
    flow._abort_if_unique_id_mismatch = MagicMock()  # type: ignore[method-assign]
    flow.async_update_reload_and_abort = MagicMock(  # type: ignore[method-assign]
        return_value={"type": "abort"}
    )
    return flow, entry


async def test_reauth_asks_for_the_secret_only() -> None:
    flow, _ = _entry_flow("reauth")
    result = await flow.async_step_reauth({})
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert list(result["data_schema"].schema) == ["app_secret"]
    assert result["description_placeholders"] == {"app_key": "key"}


async def test_reauth_updates_the_secret() -> None:
    flow, entry = _entry_flow("reauth")
    with (
        patch("custom_components.ezviz_cloud.config_flow.async_get_clientsession"),
        patch("custom_components.ezviz_cloud.config_flow.EzvizCloudApi") as api_cls,
    ):
        api_cls.return_value.async_get_token = AsyncMock()
        await flow.async_step_reauth_confirm({"app_secret": " new "})
    assert api_cls.call_args.args[1:] == ("https://ieuopen.ezvizlife.com", "key", "new")
    flow.async_update_reload_and_abort.assert_called_once_with(
        entry, data={"region": "eu", "app_key": "key", "app_secret": "new"}
    )


async def test_reauth_shows_the_error_when_rejected() -> None:
    flow, _ = _entry_flow("reauth")
    with (
        patch("custom_components.ezviz_cloud.config_flow.async_get_clientsession"),
        patch("custom_components.ezviz_cloud.config_flow.EzvizCloudApi") as api_cls,
    ):
        api_cls.return_value.async_get_token = AsyncMock(side_effect=EzvizCloudAuthError("bad"))
        result = await flow.async_step_reauth_confirm({"app_secret": "new"})
    assert result["errors"] == {"base": "invalid_auth"}
    flow.async_update_reload_and_abort.assert_not_called()


async def test_reconfigure_suggests_all_but_the_secret() -> None:
    flow, _ = _entry_flow("reconfigure")
    result = await flow.async_step_open_platform()
    assert result["step_id"] == "open_platform"
    suggested = {
        str(k): k.description["suggested_value"]
        for k in result["data_schema"].schema
        if k.description and "suggested_value" in k.description
    }
    assert suggested == {"region": "eu", "app_key": "key"}


async def test_reconfigure_updates_region_and_title() -> None:
    flow, entry = _entry_flow("reconfigure")
    with (
        patch("custom_components.ezviz_cloud.config_flow.async_get_clientsession"),
        patch("custom_components.ezviz_cloud.config_flow.EzvizCloudApi") as api_cls,
    ):
        api_cls.return_value.async_get_token = AsyncMock()
        await flow.async_step_open_platform({"region": "us", "app_key": "key", "app_secret": "s"})
    flow.async_set_unique_id.assert_awaited_once_with("key")
    flow._abort_if_unique_id_mismatch.assert_called_once()
    flow.async_update_reload_and_abort.assert_called_once_with(
        entry,
        unique_id="key",
        title="EZVIZ Cloud (US)",
        data={"region": "us", "app_key": "key", "app_secret": "s"},
    )


async def test_reconfigure_keeps_the_form_on_error() -> None:
    flow, _ = _entry_flow("reconfigure")
    with (
        patch("custom_components.ezviz_cloud.config_flow.async_get_clientsession"),
        patch("custom_components.ezviz_cloud.config_flow.EzvizCloudApi") as api_cls,
    ):
        api_cls.return_value.async_get_token = AsyncMock(side_effect=EzvizCloudError("down"))
        result = await flow.async_step_open_platform(
            {"region": "us", "app_key": "key", "app_secret": "s"}
        )
    assert result["errors"] == {"base": "cannot_connect"}
    flow.async_update_reload_and_abort.assert_not_called()


def _options_flow(
    state: ConfigEntryState = ConfigEntryState.LOADED,
    cameras: list[Camera] | None = None,
    exc: Exception | None = None,
) -> EzvizCloudOptionsFlow:
    entry = MagicMock(state=state, options={"codes": {"BK1": "OLDOLD"}})
    entry.runtime_data.account.async_cameras = AsyncMock(return_value=cameras, side_effect=exc)
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
    flow.config_entry.runtime_data.account.async_cameras = AsyncMock(
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
    assert result["menu_options"] == ["codes", "recordings", "stream"]


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


async def test_stream_step_lists_an_address_per_camera() -> None:
    flow = _options_flow()
    flow.config_entry.options["stream_token"] = "tok"
    with patch(
        "custom_components.ezviz_cloud.config_flow.get_url", return_value="http://192.168.1.10:8123"
    ):
        result = await flow.async_step_stream()
    assert result["type"] == "form"
    assert result["description_placeholders"]["urls"] == (
        "- Door: `http://192.168.1.10:8123/api/ezviz_cloud/live/BK1?token=tok`"
    )


async def test_stream_step_without_a_known_url_shows_a_placeholder() -> None:
    from homeassistant.helpers.network import NoURLAvailableError

    flow = _options_flow()
    with patch(
        "custom_components.ezviz_cloud.config_flow.get_url", side_effect=NoURLAvailableError
    ):
        result = await flow.async_step_stream()
    assert "http://HOME_ASSISTANT_IP:8123/api/" in result["description_placeholders"]["urls"]


async def test_stream_step_aborts_when_not_loaded() -> None:
    result = await _options_flow(state=ConfigEntryState.SETUP_RETRY).async_step_stream()
    assert result["reason"] == "not_loaded"


async def test_stream_step_keeps_the_token_unless_asked() -> None:
    flow = _options_flow()
    flow.config_entry.options["stream_token"] = "tok"
    result = await flow.async_step_stream({"new_token": False})
    assert result["data"] == {"codes": {"BK1": "OLDOLD"}, "stream_token": "tok"}


@pytest.mark.parametrize("state", [ConfigEntryState.LOADED, ConfigEntryState.NOT_LOADED])
async def test_stream_step_new_token_voids_the_old_addresses(state: ConfigEntryState) -> None:
    flow = _options_flow(state=state)
    flow.config_entry.options["stream_token"] = "tok"
    stream = MagicMock(token="tok")
    flow.config_entry.runtime_data.streams = {"BK1": stream}
    result = await flow.async_step_stream({"new_token": True})
    token = result["data"]["stream_token"]
    assert token != "tok"
    assert len(token) >= 32
    # A loaded entry's streams take the new token at once, without a reload.
    assert stream.token == (token if state is ConfigEntryState.LOADED else "tok")


def _ezviz_entry(
    uid: str | None, title: str, state=ConfigEntryState.LOADED, kind="EZVIZ_CLOUD_ACCOUNT"
):  # type: ignore[no-untyped-def]
    return MagicMock(unique_id=uid, title=title, state=state, data={"type": kind})


def _with_ezviz(flow: EzvizCloudConfigFlow, *entries: MagicMock) -> EzvizCloudConfigFlow:
    flow.hass.config_entries.async_entries = MagicMock(return_value=list(entries))
    return flow


async def test_app_account_needs_the_official_integration() -> None:
    flow = _with_ezviz(
        _flow(),
        _ezviz_entry("cam", "Door", kind="CAMERA_ACCOUNT"),
        _ezviz_entry("user", "Me", state=ConfigEntryState.SETUP_RETRY),
        _ezviz_entry(None, "Ignored"),
    )
    result = await flow.async_step_app_account()
    assert result["type"] == "abort"
    assert result["reason"] == "no_ezviz_account"


async def test_app_account_lists_the_official_accounts() -> None:
    flow = _with_ezviz(_flow(), _ezviz_entry("me@x", "Me"), _ezviz_entry("you@x", "You"))
    result = await flow.async_step_app_account()
    assert result["type"] == "form"
    options = result["data_schema"].schema["account"].config["options"]
    assert [(o["value"], o["label"]) for o in options] == [("me@x", "Me"), ("you@x", "You")]
    # An account that isn't listed (gone meanwhile) shows the form again.
    assert (await flow.async_step_app_account({"account": "gone"}))["type"] == "form"


async def test_app_account_creates_the_entry() -> None:
    flow = _with_ezviz(_flow(), _ezviz_entry("me@x", "Me"))
    result = await flow.async_step_app_account({"account": "me@x"})
    assert result["type"] == "create_entry"
    assert result["title"] == "EZVIZ Cloud (Me)"
    assert result["data"] == {"account": "me@x"}
    flow.async_set_unique_id.assert_awaited_once_with("ezviz_app_me@x")
    flow._abort_if_unique_id_configured.assert_called_once()


async def test_reconfigure_switches_an_app_to_the_app_account() -> None:
    flow, entry = _entry_flow("reconfigure")
    _with_ezviz(flow, _ezviz_entry("me@x", "Me"))
    flow._async_current_entries = MagicMock(return_value=[entry])  # type: ignore[method-assign]
    await flow.async_step_app_account({"account": "me@x"})
    flow.async_update_reload_and_abort.assert_called_once_with(
        entry, unique_id="ezviz_app_me@x", title="EZVIZ Cloud (Me)", data={"account": "me@x"}
    )


async def test_reconfigure_switches_the_app_account_to_an_app() -> None:
    flow, entry = _entry_flow("reconfigure", {"account": "me@x"})
    flow._async_current_entries = MagicMock(return_value=[entry])  # type: ignore[method-assign]
    result = await flow.async_step_open_platform()
    # Nothing to suggest from an app-account entry.
    assert result["type"] == "form"
    with (
        patch("custom_components.ezviz_cloud.config_flow.async_get_clientsession"),
        patch("custom_components.ezviz_cloud.config_flow.EzvizCloudApi") as api_cls,
    ):
        api_cls.return_value.async_get_token = AsyncMock()
        await flow.async_step_open_platform(dict(USER_INPUT))
    # Any app will do: the entry had none.
    flow._abort_if_unique_id_mismatch.assert_not_called()
    flow.async_update_reload_and_abort.assert_called_once_with(
        entry,
        unique_id="key",
        title="EZVIZ Cloud (EU)",
        data={"region": "eu", "app_key": "key", "app_secret": "secret"},
    )


async def test_reconfigure_refuses_an_account_another_entry_has() -> None:
    flow, entry = _entry_flow("reconfigure")
    _with_ezviz(flow, _ezviz_entry("me@x", "Me"))
    other = MagicMock(entry_id="e2", unique_id="ezviz_app_me@x")
    flow._async_current_entries = MagicMock(return_value=[entry, other])  # type: ignore[method-assign]
    with pytest.raises(AbortFlow, match="already_configured"):
        await flow.async_step_app_account({"account": "me@x"})
    flow.async_update_reload_and_abort.assert_not_called()
