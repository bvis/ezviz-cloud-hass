"""Constants for the EZVIZ Cloud integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ezviz_cloud"

CONF_APP_KEY: Final = "app_key"
CONF_APP_SECRET: Final = "app_secret"
CONF_REGION: Final = "region"

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
