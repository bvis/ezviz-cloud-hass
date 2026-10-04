"""Setup: card registration and credential handling."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from custom_components import ezviz_cloud
from custom_components.ezviz_cloud.api import EzvizCloudAuthError, EzvizCloudError
from custom_components.ezviz_cloud.const import CARD_URL

DATA = {"region": "eu", "app_key": "key", "app_secret": "secret"}


async def test_setup_serves_card_with_content_hash_url() -> None:
    hass = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn: fn())
    with (
        patch.object(ezviz_cloud, "add_extra_js_url") as add_js,
        patch.object(ezviz_cloud, "async_register_commands") as register_ws,
    ):
        assert await ezviz_cloud.async_setup(hass, {})
    (path_cfg,) = hass.http.async_register_static_paths.await_args.args[0]
    assert path_cfg.url_path == CARD_URL
    assert path_cfg.path.endswith("frontend/ezviz-cloud-live-card.js")
    digest = hashlib.sha256(Path(path_cfg.path).read_bytes()).hexdigest()[:12]
    add_js.assert_called_once_with(hass, f"{CARD_URL}?v={digest}")
    register_ws.assert_called_once_with(hass)


async def _setup_entry(side_effect: Exception | None = None) -> MagicMock:
    entry = MagicMock(data=DATA)
    with (
        patch.object(ezviz_cloud, "async_get_clientsession"),
        patch.object(ezviz_cloud, "EzvizCloudApi"),
        patch.object(ezviz_cloud, "TokenManager") as manager_cls,
    ):
        manager_cls.return_value.async_get_token = AsyncMock(side_effect=side_effect)
        assert await ezviz_cloud.async_setup_entry(MagicMock(), entry)
        assert entry.runtime_data is manager_cls.return_value
    return entry


async def test_setup_entry_keeps_manager() -> None:
    await _setup_entry()


@pytest.mark.parametrize(
    ("exc", "raised"),
    [
        (EzvizCloudAuthError("bad"), ConfigEntryError),
        (EzvizCloudError("down"), ConfigEntryNotReady),
    ],
)
async def test_setup_entry_errors(exc: Exception, raised: type[Exception]) -> None:
    with pytest.raises(raised):
        await _setup_entry(exc)


async def test_unload() -> None:
    assert await ezviz_cloud.async_unload_entry(MagicMock(), MagicMock())
