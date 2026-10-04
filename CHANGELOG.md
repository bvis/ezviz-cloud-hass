# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - unreleased

First release: live view of EZVIZ cameras through the EZVIZ Open Platform, including battery cameras with no RTSP and cameras with video encryption on.

### Added
- **Config flow for an EZVIZ Open Platform app.** Pick the region and paste the AppKey and AppSecret; they are checked before the entry is created. **Requests to EZVIZ:** one token request.
- **Live view card, served by the integration.** `custom:ezviz-cloud-live-card` plays a camera with EZVIZ's web player after you press *Watch live*, wakes battery cameras and decrypts the stream with the verification code. It stops after 60 seconds or when you leave the view. **Requests to EZVIZ:** one token request when a stream starts and the token has less than a day left.
- **Diagnostics** with the region and token expiry, credentials redacted.
