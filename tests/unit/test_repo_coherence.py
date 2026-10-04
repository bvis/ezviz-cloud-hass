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


CARD = (COMPONENT / "frontend" / "ezviz-cloud-live-card.js").read_text()
CARD_STRINGS: dict[str, dict[str, str]] = json.loads(
    re.search(r"/\* translations \*/(.*?)/\* end translations \*/", CARD, re.S).group(1)  # type: ignore[union-attr]
)


def test_card_speaks_the_integration_languages() -> None:
    integration = {p.stem for p in (COMPONENT / "translations").glob("*.json")}
    assert set(CARD_STRINGS) == integration


@pytest.mark.parametrize("lang", sorted(CARD_STRINGS))
def test_card_translations_are_complete(lang: str) -> None:
    english = CARD_STRINGS["en"]
    assert set(CARD_STRINGS[lang]) == set(english)
    for key, text in CARD_STRINGS[lang].items():
        assert re.findall(r"\{\w+\}", text) == re.findall(r"\{\w+\}", english[key]), key


def test_card_uses_exactly_its_keys() -> None:
    used = set(re.findall(r'\bt\(\w+(?:\._lang)?, "(\w+)"', CARD))
    used |= set(re.findall(r"(?:key|errorKey):[\"'](\w+)", CARD))
    used |= {f"label_{n}" for n in re.findall(r'\{ name: "(\w+)"', CARD)}
    used |= set(re.findall(r'_showProgress\(\d+, "(\w+)"', CARD))
    used |= set(re.findall(r'^\s+\[/.+/i, "(\w+)"\],$', CARD, re.M))
    assert used == set(CARD_STRINGS["en"])
