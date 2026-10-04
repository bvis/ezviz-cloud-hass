# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Recordings.** Each camera is now a device with a *Mode* select (*View* / *Record*), a *Last photo* camera and a *Last recording* sensor. In *Record* mode the card records the live view in the browser (720p) and uploads it to `media/ezviz_cloud/<serial>/`, and Home Assistant saves a full-resolution photo when the video starts. Recordings are deleted after a retention set in Configure (10 days and 100 per camera by default). **Requests to EZVIZ:** one camera list request each time the integration starts; in *Record* mode, one picture request per recording; none in *View* mode.

- **Stop and Record buttons on the card.** *Stop* ends the live view at any time; *● Record* / *■ Stop recording* start or end a recording during the live view, whatever the camera's mode. **Requests to EZVIZ:** one picture request per recording started this way.

### Changed
- **Configure is a menu** with *Verification codes* and *Recordings*, so changing the retention never touches the stored codes.
- **The integration is a hub** with one device per camera.

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
