# EZVIZ Cloud for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/bvis/ezviz-cloud-hass.svg)](https://github.com/bvis/ezviz-cloud-hass/releases)
[![Tests](https://github.com/bvis/ezviz-cloud-hass/actions/workflows/ci.yml/badge.svg)](https://github.com/bvis/ezviz-cloud-hass/actions/workflows/ci.yml)
[![Validate with hassfest](https://github.com/bvis/ezviz-cloud-hass/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/bvis/ezviz-cloud-hass/actions/workflows/hassfest.yaml)
[![HACS Validation](https://github.com/bvis/ezviz-cloud-hass/actions/workflows/validate.yaml/badge.svg)](https://github.com/bvis/ezviz-cloud-hass/actions/workflows/validate.yaml)
[![License: MIT](https://img.shields.io/github/license/bvis/ezviz-cloud-hass.svg)](LICENSE)

> **Disclaimer**: This is an **unofficial** integration, not affiliated with or endorsed by EZVIZ. It uses the public [EZVIZ Open Platform](https://ieuopen.ezviz.com) API with your own developer credentials.

Watch the live video of your EZVIZ cameras on a Home Assistant dashboard, including **battery cameras and smart peepholes that have no RTSP** and cameras with **video encryption turned on**.

The built-in EZVIZ integration plays video over local RTSP, so battery devices (which sleep and expose no RTSP port) show nothing. This integration plays the stream the way the EZVIZ app does when you're away from home: through the EZVIZ cloud. The cloud wakes the camera, and the video is decrypted in your browser with the camera's verification code. You never have to turn encryption off.

## Features

- **Live view card** (`custom:ezviz-cloud-live-card`) with a visual editor, shipped with the integration. No Lovelace resource to add by hand.
- **Wakes sleeping battery cameras** when you press *Watch live*, typically showing video within 5 seconds (up to 15 the first time a browser loads the player).
- **Works with video encryption on.** The verification code from the device label decrypts the stream in the browser.
- **Saves battery**: the stream stops after 60 seconds (configurable), when you press *Stop*, or as soon as you leave the view.
- **In your language**: English, Spanish, Catalan, French, German, Italian, Portuguese (Portugal and Brazil) and Dutch, following each Home Assistant user's language.
- **Recordings** (optional): set a camera's *Mode* to *Record* and every live view opened from the card is saved to Home Assistant's media folder, as a 720p video plus a photo, and deleted after the retention you choose. Browse them in *Media → My media → ezviz_cloud*.
- **Access token handled for you.** The token lives 7 days; the integration renews it when it's needed and keeps it out of entity states and the recorder.

## Supported devices

Any camera the EZVIZ Open Platform can play should work. Tested so far:

| Model | Type | Result |
|---|---|---|
| HP2 (`CS-HP2-R100-6E2WB-GR`) | Battery smart peephole, no RTSP | Live view works, wakes from sleep, encryption on |

If you try another model, please open an issue with the result, good or bad, so this table can grow.

## Requirements

- Home Assistant 2025.11 or newer.
- An EZVIZ account with the camera added in the EZVIZ app.
- A free EZVIZ developer account in **the same region** as your EZVIZ account, to get an AppKey and AppSecret.
- The camera's **verification code**: six capital letters on the device or its box label.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bvis&repository=ezviz-cloud-hass&category=integration)

1. In HACS, add `https://github.com/bvis/ezviz-cloud-hass` as a custom repository (category *Integration*).
2. Install **EZVIZ Cloud** and restart Home Assistant.

### Manual

Copy `custom_components/ezviz_cloud` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

### 1. Get an AppKey and AppSecret

1. Open the EZVIZ developer console for your region and sign in with your EZVIZ account, or register with the same email:

   | Region | Console |
   |---|---|
   | Europe | https://ieuopen.ezviz.com/console/home.html |
   | North America | https://iusopen.ezviz.com/console/home.html |
   | South America | https://isaopen.ezviz.com/console/home.html |
   | Singapore | https://isgpopen.ezviz.com/console/home.html |
   | India | https://iindiaopen.ezviz.com/console/home.html |
   | Vietnam | https://ivnopen.ezviz.com/console/home.html |
   | China | https://open.ys7.com |

2. Complete your developer profile if asked (an individual developer is fine).
3. Go to **Account Settings → Appkey management**. Copy the **AppKey**, then press **Check** next to the AppSecret and copy it too.

Your cameras show up under **My resources → Equipment list**. If a camera isn't there, it isn't in this EZVIZ account.

### 2. Add the integration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ezviz_cloud)

Settings → Devices & services → Add integration → **EZVIZ Cloud**. Choose your region and paste the AppKey and AppSecret. The credentials are checked before the entry is created.

### 3. Store the verification codes

On the integration, press **Configure** → **Verification codes**, pick a camera from the list and type its verification code. Repeat for each camera with encryption on. Cameras that already have a code are marked ✓; saving an empty code removes it.

The code is kept in Home Assistant's integration settings, not in the dashboard. It still reaches the browser when a stream starts, because the video is decrypted there.

### 4. Add the card

Edit a dashboard, add a card and search for **EZVIZ Cloud live**. The editor lists the cameras of your EZVIZ account. Or use YAML:

```yaml
type: custom:ezviz-cloud-live-card
title: Front door
serial: BD1234567        # device serial, from the label or the EZVIZ app
channel: 1               # optional, default 1
max_seconds: 60          # optional, default 60
```

`code: ABCDEF` still works on the card and wins over the stored one, but anyone who can open the dashboard can read it there.

### 5. Recordings (optional)

Each camera is a device with a *Mode* select (*View* or *Record*), a *Last photo* camera and a *Last recording* sensor. In *Record* mode, the card that opens the live view records it in the browser and uploads it to Home Assistant every 2 seconds, together with a photo of its first frame. Files go to `media/ezviz_cloud/<serial>/`, named after the start time.

- Only live views opened from the card are recorded. Waking the camera with its button or from the EZVIZ app isn't.
- During the live view, *● Record* / *■ Stop recording* start or end a recording on the spot, whatever the mode: switch to recording when you see something, or stop it without closing the stream.
- If two browsers open the same camera, only the first one records.
- Closing the tab keeps what was uploaded so far; the last couple of seconds may be missing.
- **Configure** → **Recordings** sets how many days to keep them (default 10) and the maximum per camera (default 100, 0 = no limit). Older ones are deleted at startup, once a day and after each new recording.
- The mode is a normal entity, so automations can switch it, for example to record only when nobody is home.

**Requests to EZVIZ:** none added: the video and the photo come from the stream the browser is already playing.

## How it works

1. When you press *Watch live*, the card asks the integration for an Open Platform access token and the camera's stored verification code over Home Assistant's authenticated websocket.
2. The card loads EZVIZ's web player ([ezuikit-js](https://www.npmjs.com/package/ezuikit-js), ISC license) and opens an `ezopen://` live address with your verification code.
3. The EZVIZ cloud wakes the camera and relays the stream to your browser, where it is decrypted and decoded (H.265 and H.264).

Video never goes through Home Assistant: it flows from the EZVIZ cloud straight to the browser showing the card. That's why the `camera` entity only shows the photo of the last recording. The Open Platform only offers HLS/RTMP addresses for cameras with encryption turned off, and this integration is built for cameras that keep it on.

**Requests to EZVIZ:** a token request and a camera list request each time the integration starts, then a token request whenever a stream starts with less than a day left on the token, so at most about one a week. Opening the card editor or the integration's Configure dialog lists the cameras (one request per 50 cameras). The live stream itself is opened by the player in the browser.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "EZVIZ rejected the AppKey/AppSecret" during setup | Check both values and the **region**. An AppKey from the European console fails against any other region with "AppKey doesn't exist". |
| The card says `EZVIZ Cloud: No loaded EZVIZ Cloud account` | The integration isn't set up or failed to load. Check Settings → Devices & services. |
| The card shows an error after "Waking camera…" | The camera didn't answer the cloud in time: check it's online in the EZVIZ app and try again. A wrong or missing verification code also fails here; check it under Configure. |
| The card isn't in the card picker | Hard-refresh the browser (the card is loaded once per page load). |

## Support

Questions and bug reports: [GitHub issues](https://github.com/bvis/ezviz-cloud-hass/issues). Please never paste your AppSecret, access token or verification code.

## Legal notice

EZVIZ is a trademark of its owner. This project is not affiliated with, endorsed by or supported by EZVIZ. It only uses the documented EZVIZ Open Platform API and web player, with credentials each user creates for their own account.

## License

[MIT](LICENSE)
