"""Diagnostics never leak credentials."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.ezviz_cloud.api import Camera
from custom_components.ezviz_cloud.diagnostics import async_get_config_entry_diagnostics


async def test_redacts_credentials() -> None:
    entry = MagicMock(
        data={"region": "eu", "app_key": "key", "app_secret": "secret"},
        options={"codes": {"BK2": "SECRET", "BK1": "SECRET"}},
    )
    entry.runtime_data.manager.api.domain = "https://ieuopen.ezvizlife.com"
    entry.runtime_data.manager.expires_at = "2026-10-11T00:00:00+00:00"
    entry.runtime_data.cameras = [Camera("BK1", 1, "Door", True)]
    entry.runtime_data.modes = {"BK1": "record"}
    result = await async_get_config_entry_diagnostics(MagicMock(), entry)
    assert result["entry"] == {
        "region": "eu",
        "app_key": "**REDACTED**",
        "app_secret": "**REDACTED**",
    }
    assert result["devices_with_code"] == ["BK1", "BK2"]
    assert "SECRET" not in str(result)
    assert result["cameras"] == [{"serial": "BK1", "name": "Door", "mode": "record"}]
    assert result["token_expires_at"] == "2026-10-11T00:00:00+00:00"
