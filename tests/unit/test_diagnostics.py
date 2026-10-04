"""Diagnostics never leak credentials."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.ezviz_cloud.diagnostics import async_get_config_entry_diagnostics


async def test_redacts_credentials() -> None:
    entry = MagicMock(data={"region": "eu", "app_key": "key", "app_secret": "secret"})
    entry.runtime_data.api.domain = "https://ieuopen.ezvizlife.com"
    entry.runtime_data.expires_at = "2026-10-11T00:00:00+00:00"
    result = await async_get_config_entry_diagnostics(MagicMock(), entry)
    assert result["entry"] == {
        "region": "eu",
        "app_key": "**REDACTED**",
        "app_secret": "**REDACTED**",
    }
    assert result["token_expires_at"] == "2026-10-11T00:00:00+00:00"
