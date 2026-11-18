# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Changed

- Standardized the public documentation around Chinese, English, and Agent entry points.
- Added local README visuals and a project-specific agent deployment guide.
- Added a multi-vendor ASR matrix with official documentation, console, and pricing links.
- Added transport, injection, and network configuration tables with official references.
- Added disclaimer, responsible-use, privacy, third-party notice, and support documents.
- Added repository-local documentation link validation to CI and the release check.
- Added a 1280x640 Social Preview image and source SVG.
- Reframed the Why now section around vibe coding, hardware programming, and a standalone speech-recognition module.
- Added lowest-cost hardware guidance and verified dependency download links for M5StickS3 and ESP32 examples.
- Added image-generation prompts without generating new visual assets.
- Added the final AI-generated images to the README hero, Why now overview, architecture section, and hardware setup guide.

### Fixed

- Provider failures now cancel the audio pump instead of waiting for an unfinished device stream.
- Stopping a session no longer blocks when the bounded audio queue is full.
- `doctor` fails when token authentication is required but no token is configured.

## [0.1.0] - 2026-11-18

### Added

- Device-agnostic stream protocol with JSON control messages and `AUD1` PCM frames.
- WebSocket, TCP, and serial transports.
- Provider adapters for Alibaba Cloud Paraformer, Deepgram, local/command-line ASR,
  and a deterministic mock provider.
- Windows SendInput and macOS text injection backends.
- Configuration, diagnostics, examples, tests, packaging metadata, and CI.