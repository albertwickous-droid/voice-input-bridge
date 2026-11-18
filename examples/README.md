# Device examples

All examples use the same stream contract:

1. Send a JSON `hello` control message.
2. Send JSON `start` with the PCM format.
3. Send binary `AUD1` frames containing little-endian PCM.
4. Send JSON `stop`; wait for `final` and `session_end`.

| Example | Transport | Notes |
| --- | --- | --- |
| `clients/python_client.py` | WebSocket or TCP | WAV, stdin, or optional `sounddevice` microphone |
| `clients/browser/index.html` | WebSocket | Zero-build browser client with Web Audio |
| `esp32/arduino_ws_mic` | WebSocket | Generic ESP32 I2S microphone and push-to-talk |
| `m5stick-s3` | WebSocket | M5Unified microphone/button reference |

Placeholders such as SSID, password, host, and token must be replaced locally.
Do not commit real credentials. Prefer a private build-time header for secrets.

The two ESP32 sketches were compiled on 2026-11-18 with ESP32 Arduino core
3.3.10, `arduinoWebSockets` 2.7.2, and the M5Unified library supplied by the
local M5StickS3 toolchain. Change board pins and microphone APIs for other
hardware.
