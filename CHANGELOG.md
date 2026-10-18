# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Capture by mode.** The camera's *Mode* gains a *Photo* option, and a new *Capture by mode* button does what the mode says: nothing in *View*, a photo in *Photo*, a clip in *Record*. Wire a doorbell to it once and switch the mode from another automation, for example to *Record* when nobody is home. The blueprint accepts it and skips the photo in the notification when nothing was captured. **Requests to EZVIZ:** none in *View*; otherwise the same as pressing *Capture photo* or *Record clip*.
- **Clip length per camera**, from 10 to 60 seconds (15 by default), for *Record clip*. **Requests to EZVIZ:** unchanged; the live stream stays open for the clip length plus about 3 seconds.

## [0.7.0] - 2026-10-17

### Added
- **Record a clip on demand, server-side.** Each camera now has a *Record clip* button next to *Capture photo*: it keeps the live stream open for 15 seconds and saves a video of about 12 seconds plus its photo, with no browser open. The video is copied into an MP4 without re-encoding (H.265 plays in Safari, Chrome and Edge). The capture blueprint accepts either button. **Requests to EZVIZ:** one live address request plus a 15-second live stream per press, the same as opening the card once.

### Fixed
- *Capture photo* could save an old image: the first couple of seconds of the stream are a picture without the camera's clock, and that was the one kept. Photos now come from the first live frame. **Requests to EZVIZ:** unchanged; the stream stays open 7 seconds instead of 4.

## [0.6.2] - 2026-10-17

### Added
- **Blueprint to capture a photo when something happens**, such as a doorbell relay, with an optional phone notification carrying the photo. Import it from the README. **Requests to EZVIZ:** the same as pressing *Capture photo*.

### Changed
- The README explains how to use *Capture photo*, where its photos end up and what to check when a capture fails.

## [0.6.1] - 2026-10-16

### Fixed
- *Capture photo* now works with H.264 cameras: the codec is read from the stream instead of assuming H.265.
- A capture can no longer hang: ffmpeg is stopped after 15 seconds and the press reports an error.
- A capture whose data ended mid-header failed with an unclear error; it now uses the frames it already has.
- A failed token request during a capture shows a normal error message.
- Pressing *Capture photo* again while a capture of the same camera is running is ignored instead of opening a second stream. **Requests to EZVIZ:** unchanged per capture; the ignored press sends none.

## [0.6.0] - 2026-10-16

### Added
- **Capture a photo on demand, server-side.** Each camera now has a *Capture photo* button that opens the live stream, keeps the first keyframe, decrypts it with pyezvizapi and saves it as the camera's last photo — with no browser open. Wire it to a doorbell relay or any automation to snapshot the visitor: the camera wakes itself when the stream opens, and the *Last photo* camera and *Last recording* sensor refresh as usual. Only the keyframe is used, so this is a still, not a video. **Requests to EZVIZ:** one live address request plus the live stream per press, the same as opening the card once; none while idle.

## [0.5.0] - 2026-10-13

### Changed
- **Requires Home Assistant 2026.10 or newer.** Schemas now use probatio, the validation library Home Assistant moved to in 2026.10, instead of voluptuous. Nothing changes in how the integration works. **Requests to EZVIZ:** none added.

## [0.4.1] - 2026-10-05

### Fixed
- **New cameras no longer need the integration to be reloaded by hand.** When the card editor or *Verification codes* lists a camera the integration has no device for yet, the account reloads and adds it. **Requests to EZVIZ:** a token and a camera list request, only when a new camera appears in a list you opened.
- **Old recordings no longer linger in *Last recording* and *Last photo*** after the daily cleanup deletes them. **Requests to EZVIZ:** none added.
- **A recording that reaches the 60 MB limit is no longer reported as failed** on the card: it is kept up to the limit and the *● Record* button comes back. **Requests to EZVIZ:** none added.
- **The same camera in two configured accounts** no longer creates duplicate entities: it stays with the first account that loads. **Requests to EZVIZ:** none added.
- **Uploads are checked before they are read**: chunks for an unknown session are refused straight away, and a body without a length stops being read past 8 MB. **Requests to EZVIZ:** none added.
- **Recording folders are created outside Home Assistant's event loop.** **Requests to EZVIZ:** none added.

## [0.4.0] - 2026-10-05

### Added
- **Recordings.** Each camera is now a device with a *Mode* select (*View* / *Record*), a *Last photo* camera and a *Last recording* sensor. In *Record* mode the card records the live view in the browser (720p) and uploads it to `media/ezviz_cloud/<serial>/`, together with a photo of its first frame. Recordings are deleted after a retention set in Configure (10 days and 100 per camera by default). **Requests to EZVIZ:** one camera list request each time the integration starts; recordings add none, since the video and the photo come from the stream the browser is already playing.

- **Stop and Record buttons on the card.** *Stop* ends the live view at any time; *● Record* / *■ Stop recording* start or end a recording during the live view, whatever the camera's mode. **Requests to EZVIZ:** none added.

### Changed
- **Configure is a menu** with *Verification codes* and *Recordings*, so changing the retention never touches the stored codes.
- **The integration is a hub** with one device per camera.
- **Diagnostics list the cameras** with their serial, name and recording mode. **Requests to EZVIZ:** none added.

## [0.3.1] - 2026-10-04

### Fixed
- **Player errors are translated.** EZVIZ's player only reports failures in English, so the card now recognises its messages (weak camera connection, camera offline, expired session, too many viewers, no permission, camera or service error) and shows them in the user's language. A message it doesn't know is still shown in English. **Requests to EZVIZ:** none added.

## [0.3.0] - 2026-10-04

### Added
- **Translations.** The card and the integration's setup and Configure dialogs are now available in English, Spanish, Catalan, French, German, Italian, Portuguese (Portugal and Brazil) and Dutch. The card follows the language of the Home Assistant user and falls back to English. Error messages that come from EZVIZ's player stay in English, because the player only has English and Chinese. **Requests to EZVIZ:** none added.

## [0.2.0] - 2026-10-04

### Added
- **Verification codes stored in the integration.** Configure on the integration lists the cameras of the account and saves each one's code, so it no longer has to be in the dashboard. A `code` on the card still works and takes precedence. **Requests to EZVIZ:** one camera list request each time the dialog opens.
- **Camera picker in the card editor.** The serial field is a dropdown with the account's cameras and says which encrypted ones have no stored code. **Requests to EZVIZ:** one camera list request each time the editor opens.
- **Diagnostics say which cameras have a stored code**, by serial only, never the code. **Requests to EZVIZ:** none added.

## [0.1.2] - 2026-10-04

### Added
- **Loading progress while the stream starts.** The card shows what it is doing (connecting, loading the decoder, waking the camera, starting the video) with a percentage until the first frame, instead of a black box for 10–15 seconds. **Requests to EZVIZ:** none added.

### Fixed
- **Player errors are shown on the card.** When the camera doesn't answer or the player fails to load, the card now says why and offers *Watch live* again; before, it stayed black until the 60-second limit. **Requests to EZVIZ:** none added.

## [0.1.1] - 2026-10-04

### Fixed
- **The card no longer overlaps the card below it in sections views.** It asked for a fixed height of 5 rows, shorter than its title plus the 16:9 video, so the next card covered the bottom of the stream. It now takes the height it needs, and the video follows the card's rounded corners. **Requests to EZVIZ:** none added.

## [0.1.0] - 2026-10-04

First release: live view of EZVIZ cameras through the EZVIZ Open Platform, including battery cameras with no RTSP and cameras with video encryption on.

### Added
- **Config flow for an EZVIZ Open Platform app.** Pick the region and paste the AppKey and AppSecret; they are checked before the entry is created. **Requests to EZVIZ:** one token request.
- **Live view card, served by the integration.** `custom:ezviz-cloud-live-card` plays a camera with EZVIZ's web player after you press *Watch live*, wakes battery cameras and decrypts the stream with the verification code. It stops after 60 seconds or when you leave the view. **Requests to EZVIZ:** one token request when a stream starts and the token has less than a day left.
- **Diagnostics** with the region and token expiry, credentials redacted.
