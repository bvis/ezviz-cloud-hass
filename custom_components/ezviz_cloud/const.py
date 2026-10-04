"""Constants for the EZVIZ Cloud integration."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

from homeassistant.util.hass_dict import HassKey

if TYPE_CHECKING:
    from .recording import RecordingSessions

DOMAIN: Final = "ezviz_cloud"

CONF_APP_KEY: Final = "app_key"
CONF_APP_SECRET: Final = "app_secret"
CONF_REGION: Final = "region"
# Options: verification codes by device serial, so they stay out of dashboards.
CONF_CODES: Final = "codes"
CONF_SERIAL: Final = "serial"
CONF_CODE: Final = "code"

# EZVIZ Open Platform API domain per account region. An appKey only works
# against the region its developer account was created in.
REGIONS: Final[dict[str, str]] = {
    "eu": "https://ieuopen.ezvizlife.com",
    "us": "https://iusopen.ezvizlife.com",
    "sa": "https://isaopen.ezvizlife.com",
    "sgp": "https://isgpopen.ezvizlife.com",
    "india": "https://iindiaopen.ezvizlife.com",
    "vn": "https://ivnopen.ezvizlife.com",
    "cn": "https://open.ys7.com",
}

# Access tokens live 7 days. Renew once less than this is left, so a viewer
# never starts a stream with a token about to expire.
TOKEN_RENEW_MARGIN: Final = timedelta(days=1)

CARD_FILENAME: Final = "ezviz-cloud-live-card.js"
CARD_URL: Final = f"/{DOMAIN}/{CARD_FILENAME}"

# Recording modes, picked per camera with the select entity.
MODE_VIEW: Final = "view"
MODE_RECORD: Final = "record"

CONF_RETENTION_DAYS: Final = "retention_days"
CONF_MAX_PER_CAMERA: Final = "max_per_camera"
DEFAULT_RETENTION_DAYS: Final = 10
DEFAULT_MAX_PER_CAMERA: Final = 100

# A 60-second stream at the card's 1.5 Mbps is about 11 MB; the caps leave room
# for longer streams without letting one session fill the disk.
MAX_SESSION_BYTES: Final = 60 * 1024 * 1024
MAX_CHUNK_BYTES: Final = 8 * 1024 * 1024
# The card sends a chunk every 2 s; this long without one means the tab is gone.
SESSION_IDLE_TIMEOUT: Final = 30
# Before the first chunk the camera may still be waking; the card itself waits
# up to its max_seconds (60 by default) for video.
FIRST_CHUNK_TIMEOUT: Final = 120


def signal_recorded(serial: str) -> str:
    """Dispatcher signal sent when a recording of this camera is saved."""
    return f"{DOMAIN}_recorded_{serial}"


# Shared by every entry: the upload view and the websocket commands find sessions here.
DATA_RECORDER: HassKey[RecordingSessions] = HassKey(DOMAIN)
