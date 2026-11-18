# Changelog

All notable changes to this project are documented here.

## [Unreleased]

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