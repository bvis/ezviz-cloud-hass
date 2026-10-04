"""The card's player-error rules recognise the texts of the pinned ezuikit-js."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CARD = (
    Path(__file__).resolve().parents[2]
    / "custom_components/ezviz_cloud/frontend/ezviz-cloud-live-card.js"
).read_text()
RULES = [
    (re.compile(pattern, re.I), key)
    for pattern, key in re.findall(r'^\s+\[/(.+)/i, "(\w+)"\],$', CARD, re.M)
]


def _classify(text: str) -> str | None:
    return next((key for rule, key in RULES if rule.search(text)), None)


@pytest.mark.parametrize(
    ("text", "key"),
    [
        (
            "Device side network is poor, please check and optimize the network and restart the device to try again",
            "err_network",
        ),
        (
            "The network on the device side is poor. Please check and optimize the network",
            "err_network",
        ),
        ("Device network abnormality, please check and optimize the network", "err_network"),
        ("Device streaming connection is disconnected, please check the network", "err_network"),
        ("Client network timeout", "err_network"),
        (
            "The device is not online, Please optimize the network and restart the device",
            "err_offline",
        ),
        ("Device does not exist, please check the device connection status", "err_offline"),
        ("Token expired, please try again", "err_token"),
        ("Token invalid, please update and retry", "err_token"),
        ("The number of simultaneous viewers has reached the maximum account limit", "err_viewers"),
        ("The current number of viewing channels has reached the maximum limit", "err_viewers"),
        ("No permission to view the current device", "err_permission"),
        ("Device abnormality, please try again or contact customer service", "err_device"),
        ("Device channel abnormality, please check the channel configuration", "err_device"),
        ("The device channel is abnormal. Please check the channel configuration", "err_device"),
        ("Device channel error", "err_device"),
        ("Service exception, please try again or contact customer service", "err_service"),
        ("Internal service exception, please try again later", "err_service"),
        ("Stream retrieval failed, please try again", "err_service"),
        ("Something EZVIZ adds later", None),
    ],
)
def test_player_error_texts_map_to_card_messages(text: str, key: str | None) -> None:
    assert _classify(text) == key
