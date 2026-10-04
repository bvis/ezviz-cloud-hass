"""Guards that keep version, supported-HA and translation declarations in sync."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "ezviz_cloud"
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())


def _keys(data: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in data.items():
        keys.add(prefix + key)
        if isinstance(value, dict):
            keys |= _keys(value, f"{prefix}{key}.")
    return keys


def test_pyproject_version_matches_manifest() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert PYPROJECT["project"]["version"] == manifest["version"]


def test_hacs_minimum_matches_dev_floor() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())["homeassistant"]
    floors = [
        m.group(1)
        for dep in PYPROJECT["project"]["optional-dependencies"]["dev"]
        if (m := re.fullmatch(r"homeassistant>=(\S+)", dep))
    ]
    assert floors == [hacs]


@pytest.mark.parametrize(
    "locale", sorted(p.stem for p in (COMPONENT / "translations").glob("*.json"))
)
def test_translation_keys_match_strings(locale: str) -> None:
    source = _keys(json.loads((COMPONENT / "strings.json").read_text()))
    target = _keys(json.loads((COMPONENT / "translations" / f"{locale}.json").read_text()))
    assert source == target
