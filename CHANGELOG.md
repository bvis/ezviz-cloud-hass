# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
