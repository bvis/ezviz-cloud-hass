# Security Policy

## Reporting a Vulnerability

Please do **not** open a public issue for a security problem. Use GitHub's [private vulnerability reporting](https://github.com/bvis/ezviz-cloud-hass/security/advisories/new) instead, with a description, steps to reproduce and the impact you see. You'll get a first answer within 48 hours.

## Supported Versions

Only the latest release gets security fixes.

## What the integration handles

- **AppKey and AppSecret** are stored in the config entry, like any other integration credential, and redacted from diagnostics.
- **The access token** is kept in memory only. It is never written to an entity state, so it doesn't end up in the recorder database. The card gets it on demand through Home Assistant's authenticated websocket.
- **Verification codes** are stored in the integration options (Configure) and kept out of diagnostics. Any logged-in Home Assistant user can get a camera's code and a token through the card's websocket command, because the browser needs both to decrypt the video. A `code` written in a card's YAML can be read by anyone who can read that dashboard's configuration. Anyone with the code and a valid token for your account can watch the camera.
- **Recordings** are files in Home Assistant's media folder. Anyone who can open the media browser can watch them, and any logged-in user who can start a live view starts a recording when the camera is in *Record* mode. Uploads only go to sessions the integration opened for that camera, are capped at 60 MB per recording, and file paths are built by the integration, never from what the browser sends. The photo is only downloaded from EZVIZ hosts.
- **The player** (`ezuikit-js`) is loaded from jsDelivr at a pinned version, inside an iframe, and talks directly to the EZVIZ cloud. Home Assistant never proxies the video.
