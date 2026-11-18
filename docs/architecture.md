# Architecture

## Components

```text
BridgeRuntime
├── HttpStatusServer             read-only /health, /v1/status, /v1/protocol
├── WebSocketTransport          JSON text + AUD1 binary
├── TcpTransport                newline JSON + AUD1 binary
├── SerialTransport             reconnecting USB CDC/ACM byte stream
├── DiscoveryTransport          optional UDP metadata responder
└── VoiceBridgeService          one active session, provider lifecycle
    ├── SessionHandle           bounded audio queue and metrics
    ├── ASRProvider             cloud, local, mock, or plugin
    ├── StreamingTextCommitter  common-prefix text edits
    └── TextSink                 Windows, macOS, clipboard, stdout, null
```

The transport layer never knows which ASR vendor is in use. The ASR layer never knows whether bytes arrived from Wi-Fi, USB, or a browser. The text layer only receives cumulative partial/final text.

## Session lifecycle

```text
STARTING
  -> create text sink
  -> instantiate provider
  -> LISTENING
  -> consume provider events
  -> FINISHING when stop or max duration is reached
  -> COMPLETED or ERROR
```

`ConnectionSession` owns the handshake and the connection-local handle. `VoiceBridgeService` owns a global lock and rejects a second simultaneous session with `busy`. This keeps foreground text ordering deterministic.

Audio enters a bounded `asyncio.Queue`. If the provider cannot keep up, the oldest queued audio is dropped and `droppedBytes` increases. The service also caps total accepted bytes with `server.max_audio_seconds`, so a malicious or broken sender cannot grow memory indefinitely.

## ASR event contract

A provider yields `TranscriptEvent` values:

```python
TranscriptEvent(text="你好", final=False, provider="demo")
TranscriptEvent(text="你好，世界。", final=True, provider="demo")
```

`StreamingTextCommitter` keeps the last partial. Given old `你好世界` and new `你好，世界。`, it backspaces the stale suffix and inserts only `，世界。`. A final event updates the current text to the provider's final version, optionally appends `input.final_suffix`, and resets the current partial.

Providers that cannot deliver cumulative partials should either emit only finals or document a segment-scoped text convention. The core deliberately does not guess how to merge arbitrary provider token streams.

## Input backends

### Windows

`WindowsSendInputSink` creates `INPUT` records with `KEYEVENTF_UNICODE`. It records the foreground window at session start and refuses to type into a different window when `require_same_window = true`. The struct layout is tested on 64-bit Windows because an incorrectly sized `INPUT` causes `SendInput` to return zero.

### macOS

`MacOSQuartzSink` records the frontmost bundle identifier, creates a Quartz keyboard event, sets its Unicode string, and posts it to the HID event tap. Accessibility permission is required. The backend is optional through the `macos` extra.

### Clipboard

`ClipboardSink` is final-only because partial pages cannot be safely revised through paste. It may replace the current clipboard. It is a compatibility fallback, not the preferred real-time backend.

## Transport details

### WebSocket

Uses `websockets.asyncio.server.serve`. Text frames are fed to the same `StreamDecoder` as binary frames after appending a newline. Binary frames must still start with `AUD1`. The server enforces idle timeout, a one-megabyte message ceiling, ping/pong, and per-client isolation.

### TCP

Uses `asyncio.start_server`. Each control line is JSON, and each `AUD1` frame is consumed exactly by its explicit length. One client exception closes only that connection.

### Serial

The optional serial transport uses pyserial in worker threads, reconnects after device loss, and accepts automatic selection of common USB VID families. A serial reconnect starts a new connection state; the device must repeat `hello` and `start`.

### Discovery

The UDP responder returns port/path/provider metadata. It intentionally contains no token, API key, transcript, or audio. Discovery is not authentication and should remain disabled unless a device actually needs it.

## Concurrency and backpressure

- One ASR session at a time.
- Multiple transport connections may exist, but only one can hold the active session.
- Audio queue depth is 64 chunks.
- Outbound serial queue depth is 256 control messages.
- WebSocket/TCP writes are serialized with a per-connection lock.
- Provider exceptions are converted to `error` events and do not kill listeners.

## Extending the project

### Add an ASR provider

1. Subclass `ASRProvider`.
2. Set `name` and `capabilities`.
3. Consume `ProviderRequest.audio` incrementally or to a bounded buffer.
4. Yield cumulative partials and final events.
5. Raise `ProviderUnavailable` for missing setup and `ProviderError` for upstream failure.
6. Register through `voicebridge.providers` entry point or add a built-in registry entry.
7. Add parser tests with captured fixture events; never call the paid API in the default suite.

### Add a text sink

1. Subclass `TextSink`.
2. Declare `InputCapabilities`.
3. Implement `start`, `insert_text`, and `backspace`.
4. Respect `require_same_window`.
5. Return `False` instead of typing when the target changes.
6. Test common-prefix edits with a fake recording sink before touching a real desktop.

### Add a transport

1. Decode bytes through `StreamDecoder`.
2. Instantiate `ConnectionSession` per peer.
3. Serialize outbound JSON writes.
4. Close the session on disconnect.
5. Isolate peer exceptions from the listener.
6. Add an end-to-end smoke test using the `mock` provider and `null` input.
