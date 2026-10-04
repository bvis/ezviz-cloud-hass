# Security Policy

## Reporting a Vulnerability

Please do **not** open a public issue for a security problem. Use GitHub's [private vulnerability reporting](https://github.com/bvis/ezviz-cloud-hass/security/advisories/new) instead, with a description, steps to reproduce and the impact you see. You'll get a first answer within 48 hours.

## Supported Versions

Only the latest release gets security fixes.

## What the integration handles

- **AppKey and AppSecret** are stored in the config entry, like any other integration credential, and redacted from diagnostics.
- **The access token** is kept in memory only. It is never written to an entity state, so it doesn't end up in the recorder database. The card gets it on demand through Home Assistant's authenticated websocket.
- **Verification codes** are stored in the integration options (Configure) and kept out of diagnostics. Any logged-in Home Assistant user can get a camera's code and a token through the card's websocket command, because the browser needs both to decrypt the video. A `code` written in a card's YAML can be read by anyone who can read that dashboard's configuration. Anyone with the code and a valid token for your account can watch the camera.
- **The player** (`ezuikit-js`) is loaded from jsDelivr at a pinned version, inside an iframe, and talks directly to the EZVIZ cloud. Home Assistant never proxies the video.
