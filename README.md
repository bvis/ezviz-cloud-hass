# EZVIZ Cloud for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/bvis/ezviz-cloud-hass.svg)](https://github.com/bvis/ezviz-cloud-hass/releases)
[![Tests](https://github.com/bvis/ezviz-cloud-hass/actions/workflows/ci.yml/badge.svg)](https://github.com/bvis/ezviz-cloud-hass/actions/workflows/ci.yml)
[![Validate with hassfest](https://github.com/bvis/ezviz-cloud-hass/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/bvis/ezviz-cloud-hass/actions/workflows/hassfest.yaml)
[![HACS Validation](https://github.com/bvis/ezviz-cloud-hass/actions/workflows/validate.yaml/badge.svg)](https://github.com/bvis/ezviz-cloud-hass/actions/workflows/validate.yaml)
[![License: MIT](https://img.shields.io/github/license/bvis/ezviz-cloud-hass.svg)](LICENSE)
[![Quality scale: Platinum (self-assessed)](https://img.shields.io/badge/quality%20scale-platinum%20(self--assessed)-8a9ba8)](custom_components/ezviz_cloud/quality_scale.yaml)

> **Disclaimer**: This is an **unofficial** integration, not affiliated with or endorsed by EZVIZ. It uses the public [EZVIZ Open Platform](https://ieuopen.ezviz.com) API with your own developer credentials.

Watch the live video of your EZVIZ cameras on a Home Assistant dashboard, including **battery cameras and smart peepholes that have no RTSP** and cameras with **video encryption turned on**.

The built-in EZVIZ integration plays video over local RTSP, so battery devices (which sleep and expose no RTSP port) show nothing. This integration plays the stream the way the EZVIZ app does when you're away from home: through the EZVIZ cloud. The cloud wakes the camera, and the video is decrypted in your browser with the camera's verification code. You never have to turn encryption off.

## Features

- **Live view card** (`custom:ezviz-cloud-live-card`) with a visual editor, shipped with the integration. No Lovelace resource to add by hand.
- **A live camera entity** too, for everything that isn't the card: any camera card, the live view in an iPhone notification when the doorbell rings, HomeKit and other bridges. It streams only while someone watches.
- **Wakes sleeping battery cameras** when you press *Watch live*, typically showing video within 5 seconds (up to 15 the first time a browser loads the player).
- **Works with video encryption on.** The verification code from the device label decrypts the stream in the browser.
- **Saves battery**: the stream stops after 60 seconds (configurable), when you press *Stop*, or as soon as you leave the view.
- **In your language**: English, Spanish, Catalan, French, German, Italian, Portuguese (Portugal and Brazil) and Dutch, following each Home Assistant user's language.
- **Photos and clips, saved in Home Assistant** (optional): record what the card shows, or press a button (from a dashboard or an automation, no browser needed) to save a photo or a clip. Everything shows up in *Media → EZVIZ Cloud*, one folder per camera, and old files are deleted after the retention you choose.
- **One button for the doorbell**: *Capture by mode* takes a photo, records a clip or does nothing depending on the camera's *Mode*, so an automation can decide what a ring does, for example record only when nobody is home. A ready-made [blueprint](#8-capture-from-an-automation-optional) does the wiring and can send the photo to your phone.
- **Access token handled for you.** The token lives 7 days; the integration renews it when it's needed and keeps it out of entity states and the recorder.

## Supported devices

Any camera the EZVIZ Open Platform can play should work. Tested so far:

| Model | Type | Result |
|---|---|---|
| HP2 (`CS-HP2-R100-6E2WB-GR`) | Battery smart peephole, no RTSP, H.265 | Live view (card and live camera), recordings, *Capture photo* and *Record clip* work, wakes from sleep, encryption on |

If you try another model, please open an issue with the result, good or bad, so this table can grow.

## Requirements

- Home Assistant 2026.10 or newer.
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

Settings → Devices & services → Add integration → **EZVIZ Cloud**. Choose your region and paste the AppKey and AppSecret. The credentials are checked before the entry is created. To change the region or the AppSecret later, use **Reconfigure** on the integration. If EZVIZ stops accepting the AppSecret, Home Assistant asks for the new one.

### 3. Store the verification codes

On the integration, press **Configure** → **Verification codes**, pick a camera from the list and type its verification code. Repeat for each camera with encryption on. Cameras that already have a code are marked ✓; saving an empty code removes it.

Saving checks the code against the camera's video, which wakes it and takes up to 20 seconds. A code that doesn't decrypt the video is refused. If the camera doesn't answer, or is streaming right then, the code is saved without the check.

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

### 5. The live camera (optional)

Each camera also gets a **Live** camera entity (`camera.<name>_live`). Use it where the card can't go: a *Picture entity* or *Picture glance* card, the live view in a notification (see [section 8](#8-capture-from-an-automation-optional)), HomeKit or any other bridge. Its picture is the last saved photo, so a dashboard never wakes the camera; the video starts when you open it.

Home Assistant plays it through go2rtc (WebRTC) or its own HLS player, both included in a default install. The video is the camera's own H.265 (or H.264), not re-encoded, so it costs Home Assistant almost no CPU; the browser or phone has to play H.265, as with the clips.

The live camera, *Capture photo* and *Record clip* share one stream per camera: a clip recorded while you watch, or a notification opened during a clip, opens the camera once. The stream closes 20 seconds after the last viewer leaves. If the camera doesn't answer, it isn't asked again for a minute.

**Requests to EZVIZ:** one live address request plus the live stream while someone watches (and 20 seconds more). Nothing while nobody watches.

### 6. Photos and recordings (optional)

Each camera is a device with these entities:

| Entity | What it's for |
|---|---|
| *Mode* | *View*, *Photo* or *Record*: what the card and *Capture by mode* do (see below). |
| *Capture photo* | Saves a photo now. |
| *Record clip* | Saves a video now, as long as *Clip length*, plus its photo. |
| *Capture by mode* | Does what the *Mode* says. Wire your doorbell to this one. |
| *Clip length* | Length of the clips, 10 to 60 seconds (15 by default). |
| *Last photo* | Camera entity that shows the newest photo. |
| *Last recording* | When the newest photo or video was saved. |

What the *Mode* changes:

| Mode | When someone opens the card's live view | When *Capture by mode* is pressed |
|---|---|---|
| *View* | Nothing is saved | Nothing happens |
| *Photo* | Nothing is saved | A photo is saved |
| *Record* | The live view is recorded, with a photo | A clip is recorded, with a photo |

The mode is a normal entity, so an automation can switch it, for example to *Record* when everybody leaves and back to *View* or *Photo* when someone gets home.

#### Where to find them

Open **Media → EZVIZ Cloud** in the sidebar. There's a folder per camera, with its name, and inside it everything that camera saved, newest first, titled with the date and time. Clips show their photo as the thumbnail; tap one to play it. A camera's folder appears once it has saved something.

**Configure** → **Recordings** sets how many days to keep them (default 10) and the maximum per camera (default 100, 0 = no limit). Older ones are deleted at startup, once a day and after each new one.

The files are in Home Assistant's media folder, under `ezviz_cloud/<serial>/`, if you want to copy them elsewhere (Samba, a backup). The *Last recording* sensor's `video` and `photo` attributes hold their `media-source://` addresses, handy for notifications.

#### Recording from the card

In *Record* mode, the card records the live view in the browser and sends it to Home Assistant as it plays: a 720p video plus a photo of its first frame.

- During the live view, *● Record* / *■ Stop recording* start or end a recording on the spot, whatever the mode: start recording when you see something, or stop it without closing the stream.
- *Stop* and leaving the view keep the whole recording. Closing the tab keeps what was sent so far, which can miss the last few seconds.
- If two browsers open the same camera, only the first one records.
- Watching from the EZVIZ app isn't recorded.

**Requests to EZVIZ:** none added: the video and the photo come from the stream the browser is already playing.

#### Photos and clips without the card

The *Capture photo*, *Record clip* and *Capture by mode* buttons work with no browser open, from a dashboard or an automation. *Capture photo* wakes the camera and saves a photo after about 15 to 20 seconds. *Record clip* saves a video of the camera's *Clip length* plus its photo, about 15 seconds after the clip ends. *Last photo* and *Last recording* update right away.

Pressing a button while another capture of the same camera is running does nothing, so a long press or a double ring makes one photo or clip.

Clips are the camera's own H.265 (or H.264) video, not re-encoded, so they cost Home Assistant almost no CPU. Safari, Chrome and Edge play H.265 on most devices, and so does the Home Assistant app where the phone supports it; Firefox on desktop may not.

**Requests to EZVIZ:** each press opens the camera's live stream once (one live address request plus the stream, for a few seconds for a photo or the clip length plus a few for a clip), the same as opening the card. If the live camera is already streaming, the press reads that stream and makes none. *Capture by mode* in *View* makes none.

### 7. Buttons on a dashboard (optional)

The quickest way to try the buttons is the camera's device page (Settings → Devices & services → EZVIZ Cloud → your camera). To have them on a dashboard, add a tile per button; tapping it presses the button. This example also shows the last photo, and both open the camera's folder in *Media*:

```yaml
type: grid
cards:
  - type: tile
    entity: button.front_door_capture_by_mode
    tap_action:
      action: perform-action
      perform_action: button.press
      target:
        entity_id: button.front_door_capture_by_mode
    grid_options:
      columns: 12
  - type: tile
    entity: select.front_door_mode
  - type: tile
    entity: number.front_door_clip_length
  - type: picture-entity
    entity: camera.front_door_last_photo
    show_state: false
    tap_action:
      action: navigate
      navigation_path: /media-browser/browser/app%2Cmedia-source%3A%2F%2Fezviz_cloud/%2Cmedia-source%3A%2F%2Fezviz_cloud%2FBD1234567
```

Change the entity ids to your camera's, and `BD1234567` at the end of `navigation_path` to its serial. *Capture photo* and *Record clip* go in tiles the same way as *Capture by mode*.

### 8. Capture from an automation (optional)

To capture when the doorbell rings, import the blueprint:

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fbvis%2Fezviz-cloud-hass%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fezviz_cloud%2Fcapture_photo.yaml)

Then create an automation from it and pick:

- **Trigger**: the entity that should start the capture, such as the doorbell relay's binary sensor, and the state to react to (`on` by default; leave it empty for an event entity).
- **Capture button**: the camera's *Capture by mode* (recommended, so the *Mode* decides), *Capture photo* or *Record clip*.
- Optionally a **notify action** from the Home Assistant app (`notify.mobile_app_<phone>`), and either:
  - the camera's **Last photo** entity: the notification arrives once the capture is saved, with the photo. When *Capture by mode* saved nothing (*View*), it goes without a photo; or
  - the camera's **Live** entity: the notification goes out right away, before the capture, and opening it on an iPhone plays the camera live. The capture shares the same stream. Android shows a picture instead of the live view.

If you'd rather write the automation yourself, this sends the live view first and then records a clip:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.doorbell
    to: "on"
actions:
  - action: notify.mobile_app_my_phone
    data:
      message: Someone is at the door
      data:
        entity_id: camera.front_door_live   # the iPhone app plays it live
  - action: button.press
    target:
      entity_id: button.front_door_record_clip
```

Or, with the photo in the notification:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.doorbell
    to: "on"
actions:
  - action: button.press          # returns once the photo is saved
    target:
      entity_id: button.front_door_capture_photo
  - action: notify.mobile_app_my_phone
    data:
      message: Someone is at the door
      data:
        image: /api/camera_proxy/camera.front_door_last_photo
```

## How it works

1. When you press *Watch live*, the card asks the integration for an Open Platform access token and the camera's stored verification code over Home Assistant's authenticated websocket.
2. The card loads EZVIZ's web player ([ezuikit-js](https://www.npmjs.com/package/ezuikit-js), ISC license) and opens an `ezopen://` live address with your verification code.
3. The EZVIZ cloud wakes the camera and relays the stream to your browser, where it is decrypted and decoded (H.265 and H.264).

With the card, video never goes through Home Assistant: it flows from the EZVIZ cloud straight to the browser. The Open Platform only offers HLS/RTMP addresses for cameras with encryption turned off, and this integration is built for cameras that keep it on.

The live camera and the *Capture photo* and *Record clip* buttons open the same `ezopen` stream inside Home Assistant instead, decrypt it with [pyezvizapi](https://pypi.org/project/pyezvizapi/) and hand it to ffmpeg: one frame for a photo, a copy into an MP4 for a clip, a copy into MPEG-TS on a local address that go2rtc and Home Assistant's stream player read for the live camera. That address only answers with a random token that changes at every restart. The first couple of seconds the cloud sends don't decode and carry no on-screen clock; they are skipped, so video starts at the first live frame.

**Requests to EZVIZ:** a token request and a camera list request each time the integration starts, then a token request whenever a stream starts with less than a day left on the token, so at most about one a week. Opening the card editor or the *Verification codes* dialog lists the cameras (one request per 50 cameras). If that list has a camera the integration has no device for, the account reloads to add it (a token and a camera list request). The card's live stream is opened by the player in the browser. The live camera and each press of *Capture photo* or *Record clip* add one live address request plus the live stream, shared between them, kept while it is read and 20 seconds after. Saving a verification code opens it once to check the code.

## Limitations

- **Everything goes through the EZVIZ cloud.** Video travels from the camera to EZVIZ and back, so it needs internet and EZVIZ's servers, and has a few seconds of delay. Nothing works locally.
- **EZVIZ limits streams.** A camera plays one stream at a time, and some battery cameras refuse a new one for a few minutes after the last. The card and the live camera are separate streams: watching both at once fails on such cameras.
- **Battery.** Every live view, photo and clip wakes a battery camera. Watch in short sessions.
- **H.265 needs a player that supports it** (Safari, Chrome, Edge, the Home Assistant app on most phones); the integration doesn't re-encode.
- **Live view in notifications** works on the iPhone Home Assistant app. On Android the notification shows a picture.
- **Only live video.** Recordings stored by EZVIZ (cloud or SD card) aren't browsable here; only what this integration saved.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "EZVIZ rejected the AppKey/AppSecret" during setup | Check both values and the **region**. An AppKey from the European console fails against any other region with "AppKey doesn't exist". |
| The card says `EZVIZ Cloud: No loaded EZVIZ Cloud account` | The integration isn't set up or failed to load. Check Settings → Devices & services. |
| The card shows an error after "Waking camera…" | The camera didn't answer the cloud in time: check it's online in the EZVIZ app and try again. A wrong or missing verification code also fails here; check it under Configure. |
| The card shows "Couldn't save the recording" | Another browser is already recording that camera, this browser can't record the player's video, or Home Assistant couldn't write the file (check the log). |
| The card isn't in the card picker | Hard-refresh the browser (the card is loaded once per page load). |
| *Capture photo* or *Record clip* fails with "No video received; the camera may be asleep" | The camera didn't answer within 20 seconds. Check it's online in the EZVIZ app and press again. |
| *Capture photo* fails with "Could not decode a keyframe" | Usually a wrong verification code: check it under Configure. If the code is right, please open an issue with the camera model. |
| A capture fails with "The stream ended before its first keyframe" | The camera stopped streaming after a couple of seconds. Press again; if it keeps happening, please open an issue with the camera model. |
| A capture or the live camera fails with "Stream error 5405" | The camera didn't answer the cloud. Some battery cameras refuse a new stream for a few minutes after the last one, or need waking by hand: wake it and try again. |
| The live camera doesn't play in the browser or the phone | It can't play H.265. Use Safari, Chrome or Edge, or the Home Assistant app on a phone that supports it. |
| A camera has no folder in *Media → EZVIZ Cloud* | It hasn't saved anything yet, or everything it saved was deleted by the retention. Press *Capture photo* to check. |
| The clip doesn't play in the browser | The browser can't play H.265. Open it in Safari, Chrome or Edge, or in the Home Assistant app. |

## Removal

1. Settings → Devices & services → EZVIZ Cloud → ⋮ → **Delete**.
2. In HACS, open EZVIZ Cloud → ⋮ → **Remove**, then restart Home Assistant.
3. Photos and recordings stay in `<media>/ezviz_cloud/`. Delete that folder if you don't want them.
4. Optionally, delete the application in the EZVIZ developer console so its AppKey stops working.

## Quality scale

[`quality_scale.yaml`](custom_components/ezviz_cloud/quality_scale.yaml) lists every rule of Home Assistant's [integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/) with its status here. Rules marked `todo` link to the issue that tracks them.

## Support

Questions and bug reports: [GitHub issues](https://github.com/bvis/ezviz-cloud-hass/issues). Please never paste your AppSecret, access token or verification code.

This integration is free and open source, and stays that way — every feature is available to everyone. If it's useful to you and you'd like to support the time that goes into maintaining it, you can [buy me a coffee](https://buymeacoffee.com/basiliovera) ☕. Entirely optional and always appreciated.

## Legal notice

EZVIZ is a trademark of its owner. This project is not affiliated with, endorsed by or supported by EZVIZ. It only uses the documented EZVIZ Open Platform API and web player, with credentials each user creates for their own account.

## License

[MIT](LICENSE)
