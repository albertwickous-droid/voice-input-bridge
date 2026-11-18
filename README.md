# Voice Input Bridge

**Turn any device that can capture PCM audio into a real-time Windows/macOS dictation source.**

Voice Input Bridge (`vib`) is a small, provider-neutral speech-to-text daemon. An ESP32, M5Stick, browser, phone, or script streams PCM over WebSocket or TCP. The bridge sends it to a cloud or local ASR provider, receives partial and final text, and injects the result into the current text field.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-alpha-orange)

> The default listener binds to `127.0.0.1`. A token authenticates clients but does **not** encrypt traffic. Use a LAN/firewall boundary, WireGuard/Tailscale, or a TLS reverse proxy before exposing it to an untrusted network.

## Why this exists

Most dictation tools assume a keyboard, a specific operating system, or one cloud vendor. This project makes the missing part explicit:

```text
microphone / device
        |
        | PCM over WebSocket, TCP, or USB serial
        v
+-------------------- voice-input-bridge --------------------+
| connection -> framing -> session -> ASR provider -> text  |
+------------------------------------------------------------+
        |                                      |
        | partial/final events                 | SendInput / Quartz
        v                                      v
 status clients                         foreground text field
```

The transport, ASR provider, and text-injection backend are independent. You can use Alibaba Cloud in one deployment, Deepgram in another, a local command-line ASR tool offline, or a third-party provider plugin without changing the device firmware.

## Features

- WebSocket, TCP, optional USB serial, and optional UDP discovery.
- PCM S16LE audio with a compact `AUD1` binary frame.
- Real-time partial results and final transcripts.
- Minimal partial-text revisions using a common-prefix diff.
- Windows Unicode text injection through Win32 `SendInput`.
- macOS Unicode text injection through Quartz, with clipboard fallback.
- Built-in providers: `mock`, `aliyun`, `deepgram`, and `command`.
- Provider plugins through the `voicebridge.providers` Python entry point.
- Read-only HTTP health, status, and protocol endpoints.
- CLI diagnostics (`doctor`), protocol simulator, and safe secret redaction.
- No automatic `.env` loading: credentials are explicit environment variables or config references.

## Quick start (safe demo)

This path uses the deterministic `mock` provider and does not type into your foreground window.

```bash
# Replace YOUR_GITHUB_USER after creating the repository.
git clone https://github.com/YOUR_GITHUB_USER/voice-input-bridge.git
cd voice-input-bridge
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"

voicebridge doctor --config config.demo.toml
voicebridge serve --config config.demo.toml
```

In another terminal:

```bash
voicebridge simulate --target ws://127.0.0.1:18766/v1/audio
```

You should see `partial`, `final`, and `session_end` JSON events. The HTTP endpoints are:

- `http://127.0.0.1:18765/health`
- `http://127.0.0.1:18765/v1/status`
- `http://127.0.0.1:18765/v1/protocol`

## Enable real text injection

Copy the example and choose a provider and input backend:

```bash
cp config.example.toml config.toml
# Windows PowerShell: Copy-Item config.example.toml config.toml
```

For Windows Unicode typing:

```toml
[input]
backend = "windows"
send_partial = true
require_same_window = true
```

For macOS:

```toml
[input]
backend = "macos"
```

The bridge starts a session against the foreground window/application. If the foreground changes and `require_same_window = true`, text updates pause instead of being typed into the wrong app.

### Windows permissions

Use the same integrity level as the target application. A non-elevated bridge cannot inject into an elevated terminal or another elevated process. The binary must also be allowed to run; some security products restrict `SendInput`.

### macOS permissions

Grant the Python interpreter or packaged app **Accessibility** permission in System Settings. The Quartz backend requires it. The `clipboard` backend is final-only, may overwrite the current clipboard, and cannot enforce `require_same_window`; it therefore requires `input.require_same_window = false` explicitly.

## Provider selection

| Provider | Streaming | Credentials | Best fit |
| --- | --- | --- | --- |
| `mock` | partial + final | none | CI, protocol tests, installation checks |
| `aliyun` | partial + final | DashScope API key | Chinese real-time dictation |
| `deepgram` | partial + final | Deepgram API key | multilingual/global real-time dictation |
| `command` | final only | depends on command | whisper.cpp, faster-whisper, FunASR, Vosk, vendor CLIs |
| plugin | capability-defined | package-defined | custom or self-hosted ASR |

Example Alibaba Cloud configuration:

```toml
[asr]
provider = "aliyun"

[asr.aliyun]
model = "paraformer-realtime-v2"
api_key = "${DASHSCOPE_API_KEY}"
workspace_id = "${DASHSCOPE_WORKSPACE_ID}"
vocabulary_id = "${DASHSCOPE_VOCABULARY_ID:-}"
language_hints = ["zh", "en"]
```

```powershell
$env:DASHSCOPE_API_KEY = "..."
$env:DASHSCOPE_WORKSPACE_ID = "..."
voicebridge doctor --config config.toml
voicebridge serve --config config.toml
```

Never put a real key in a committed TOML file, issue, screenshot, or chat message. Provider pricing, quotas, and model availability change; use the official provider console and pricing pages linked in [docs/providers.md](docs/providers.md).

## Device protocol at a glance

All control messages are JSON objects. Binary audio uses an 8-byte header and a 16-bit little-endian payload length:

```text
41 55 44 31  LL LL  SS SS  <PCM payload>
A  U  D  1  length  seq
```

Typical WebSocket flow:

```json
{"type":"hello","token":""}
{"type":"start","sampleRate":16000,"channels":1,"bitsPerSample":16,"encoding":"pcm_s16le","language":"zh-CN"}
```

Then send binary `AUD1` frames, followed by:

```json
{"type":"stop"}
```

The server emits `partial`, `final`, `warning`, `error`, `stopped`, and `session_end` messages. See [docs/protocol.md](docs/protocol.md) for the complete contract and error behavior.

## Examples

- [Python client](examples/clients/python_client.py) — WebSocket/TCP, WAV/stdin/microphone.
- [Browser client](examples/clients/browser/index.html) — Web Audio capture with no build step.
- [Generic ESP32 I2S example](examples/esp32/arduino_ws_mic/arduino_ws_mic.ino).
- [M5StickS3 reference](examples/m5stick_s3_ws_dictation/m5stick_s3_ws_dictation.ino).

For the browser example, serve the directory over local HTTP rather than opening `file://` directly:

```bash
python -m http.server 8000 --directory examples/clients/browser
```

Then open `http://127.0.0.1:8000`. Browsers require a secure context for microphone access; `127.0.0.1` is treated as localhost. If the page is served over HTTPS, connect to `wss://` instead of `ws://`.

## CLI

```text
voicebridge serve      Start HTTP, WebSocket, TCP, serial, and discovery services
voicebridge doctor     Check platform, dependencies, credentials, input, and ports
voicebridge simulate   Send synthetic PCM through a local endpoint
voicebridge config     Print effective configuration with secrets redacted
voicebridge providers  List built-in and installed providers
```

Useful commands:

```bash
voicebridge doctor --config config.toml --json
voicebridge simulate --target tcp://127.0.0.1:18767 --seconds 1
voicebridge config --config config.toml --json
```

## Configuration

The complete example is [config.example.toml](config.example.toml). Important rules:

- `${VAR}` expands from the process environment; `${VAR:-default}` supplies a default.
- The application does not automatically read `.env`.
- `server.require_token = true` without a token rejects every client.
- `server.host` controls WebSocket/TCP/serial discovery binding; `http_host` controls HTTP.
- The service accepts one active ASR session at a time; additional sessions receive `busy`.
- `server.max_audio_seconds` caps a session and drops excess audio rather than growing memory without bound.
- Partial text is enabled by default. Set `input.send_partial = false` for final-only injection.

## Security and privacy

Read [SECURITY.md](SECURITY.md) before exposing the bridge beyond loopback. Important defaults:

- HTTP/WebSocket/TCP bind to loopback by default.
- HTTP status redacts transcript text and never returns tokens or API keys.
- Audio is not written to disk by the core service.
- The `command` provider writes a temporary WAV because command-line ASR tools normally require a file; it is deleted when the command finishes.
- Provider credentials are sent only to the configured provider endpoint.
- A static token is not a substitute for TLS.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest -q
python -m build
twine check dist/*
```

The default suite uses `mock`, `null` input, random loopback ports, and no paid APIs. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Current limitations

- The project is alpha; provider event schemas can change upstream.
- `command` and most local Whisper wrappers are final-only because they receive a completed WAV.
- Browser `ScriptProcessorNode` is used for broad compatibility; production web clients may prefer an AudioWorklet.
- The macOS Quartz backend needs real-device validation on each supported macOS release.
- The supplied ESP32 sketches are references; microphone pins and board APIs must match your hardware.
- UDP discovery returns metadata only. It does not discover across subnets or authenticate responses.

## License

MIT. See [LICENSE](LICENSE).
