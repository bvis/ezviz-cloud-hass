# Security Policy

## Reporting a Vulnerability

Please do **not** open a public issue for a security problem. Use GitHub's [private vulnerability reporting](https://github.com/bvis/ezviz-cloud-hass/security/advisories/new) instead, with a description, steps to reproduce and the impact you see. You'll get a first answer within 48 hours.

## Supported Versions

Only the latest release gets security fixes.

## What the integration handles

- **AppKey and AppSecret** are stored in the config entry, like any other integration credential, and redacted from diagnostics.
- **The access token** is kept in memory only. It is never written to an entity state, so it doesn't end up in the recorder database. The card gets it on demand through Home Assistant's authenticated websocket.
- **Verification codes** are stored in the integration options (Configure) and kept out of diagnostics. Only Home Assistant administrators can get a camera's code and a token, through the card's websocket command, because the browser needs both to decrypt the video. Other users watch through the live camera entity, which never hands them either. A `code` written in a card's YAML can be read by anyone who can read that dashboard's configuration. Anyone with the code and a valid token for your account can watch the camera.
- **Recordings** are files in Home Assistant's media folder. Anyone who can open the media browser can watch them, and only administrators can record from the card's player: automatically when the camera is in *Record* mode, or with the card's *● Record* button whatever the mode. Other users record with the *Record clip* and *Capture photo* buttons, under Home Assistant's own permissions. Uploads only go to sessions the integration opened for that camera, are capped at 60 MB per recording, and file paths are built by the integration, never from what the browser sends.
- **The stream address for other apps** (*Configure → Stream address for other apps*) needs no Home Assistant login: a random token in the address is all that guards it, because go2rtc, Frigate and Home Assistant's own stream reader can't log in. Anyone who has an address can watch that camera, and wake it, from wherever your Home Assistant can be reached, the internet included if you expose it. The token is stored in the integration options, stays the same across restarts and is kept out of diagnostics and entity attributes. *Make new addresses* replaces it; a reader that is already connected keeps its stream until it disconnects. Treat a log from an app you pasted the address into as you would the address.
- **The EZVIZ app account** mode keeps no EZVIZ credential of its own. It reuses the session of Home Assistant's built-in EZVIZ integration, which stores and renews it, and asks EZVIZ for a stream with it. Diagnostics redact the account name.
- **The player** (`ezuikit-js` 9.0.23, unmodified) and its decoder files ship with the integration and are served by Home Assistant, so nothing is loaded from a CDN. They run inside a sandboxed iframe with an origin of its own and talk directly to the EZVIZ cloud. Home Assistant never proxies the card's video.
