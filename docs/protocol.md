# Voice Input Bridge protocol, version 1

The protocol is transport-independent. WebSocket, TCP, and serial use the same control messages and audio frames. A single connection has one authentication state and at most one active ASR session.

## Transports

| Transport | Default | Framing |
| --- | --- | --- |
| HTTP status | `127.0.0.1:18765` | HTTP/1.1 GET |
| WebSocket | `127.0.0.1:18766/v1/audio` | JSON text frames and binary `AUD1` frames |
| TCP | `127.0.0.1:18767` | newline JSON and binary `AUD1` frames |
| USB serial | disabled | same byte stream as TCP |
| UDP discovery | disabled, `18768` | request/response datagram |

A WebSocket JSON text message may omit the trailing newline. TCP and serial control messages must be terminated by `\n`. CRLF is accepted.

## Authentication

When `server.require_token = false`, a client may send `hello` with an empty token. When it is `true`, the token is compared in constant time and a missing or incorrect token is rejected.

```json
{"type":"hello","token":"your-token"}
```

Successful response:

```json
{
  "type":"hello_ack",
  "ok":true,
  "service":"voice-input-bridge",
  "protocol":1,
  "requiresToken":true,
  "providers":["aliyun"]
}
```

The token is transmitted in clear text unless the transport itself is encrypted. Use WebSocket over a TLS reverse proxy (`wss://`) or a private VPN when the network is not trusted.

## Start a session

After `hello_ack`, send:

```json
{
  "type":"start",
  "sampleRate":16000,
  "channels":1,
  "bitsPerSample":16,
  "encoding":"pcm_s16le",
  "language":"zh-CN",
  "sessionId":"optional-client-id"
}
```

Required audio properties are sent explicitly. The bridge currently accepts any PCM format allowed by `AudioFormat`, but individual ASR providers may reject unsupported formats. The built-in Aliyun and Deepgram adapters require 16-bit PCM; Aliyun accepts mono 8 kHz or 16 kHz, while Deepgram accepts the configured sample rate and channel count.

A successful start produces:

```json
{"type":"listening","sessionId":"...","provider":"aliyun","audio":{...}}
```

Only one ASR session can be active across the whole bridge at a time. A second start receives:

```json
{"type":"error","code":"busy","message":"session ... is already active"}
```

## Audio frame format

Each binary message is one audio frame. The header is exactly 8 bytes:

| Offset | Size | Meaning |
| --- | --- | --- |
| 0 | 4 | ASCII magic `AUD1` |
| 4 | 2 | payload length in bytes, little-endian unsigned 16-bit |
| 6 | 2 | sequence number, little-endian unsigned 16-bit |
| 8 | N | PCM payload |

```text
41 55 44 31  LL LL  SS SS  <N bytes PCM>
A  U  D  1  length  seq
```

The current encoder rejects payloads above 65,535 bytes. A 20 ms mono 16 kHz S16LE audio frame is 640 bytes, which is the recommended device chunk size. Sequence numbers wrap at 65,535 and are informational in protocol version 1.

Audio may span arbitrary network chunks. Do not send a raw PCM WebSocket binary message without an `AUD1` header. Audio before `start`, after `stop`, or before successful authentication is rejected with an error.

## Finish a session

Send:

```json
{"type":"stop"}
```

No more audio should follow. The provider may emit final results and the server eventually sends:

```json
{
  "type":"session_end",
  "session":{
    "sessionId":"...",
    "state":"completed",
    "frames":25,
    "bytesReceived":16000,
    "finals":1,
    "lastFinal":"...",
    "firstPartialMs":180.4
  }
}
```

The connection-level `stopped` message follows the service-level `session_end` when the stop was requested with the `stop` control message.

## Server transcript events

Partial result:

```json
{"type":"partial","text":"你好，世","provider":"aliyun"}
```

Final result:

```json
{"type":"final","text":"你好，世界。","provider":"aliyun"}
```

Treat `partial` as cumulative text for the current utterance unless a provider plugin explicitly documents otherwise. The bridge computes the common prefix with the previous partial, backspaces only the stale suffix, and types only the new suffix.

Final events may occur more than once per session when a provider commits multiple sentences. A plugin should emit event text in the provider's segment scope and document that behavior.

Other server messages:

| Type | Meaning |
| --- | --- |
| `warning` | Non-fatal condition such as a max-duration limit or no final result |
| `error` | Protocol, authentication, provider, or internal failure |
| `stopped` | Response to the `stop` control message |
| `session_end` | Session lifecycle finished; metrics are included |
| `pong` | Response to `ping` |
| `status` | Response to `status` or `get_status` |

Example warnings:

```json
{"type":"warning","code":"provider_no_final","message":"ASR stream ended without a final transcript","sessionId":"..."}
{"type":"warning","code":"text_input_paused","message":"foreground window changed","sessionId":"..."}
```

## Errors and close behavior

The server sends an error before closing for protocol violations:

```json
{"type":"error","code":"protocol_error","message":"expected an AUD1 frame or a JSON value"}
```

Error codes are stable strings, not localized UI text. Clients should display `message` but branch on `code`.

| Code | Typical cause |
| --- | --- |
| `unauthorized` | No valid `hello` before a protected operation |
| `busy` | Another session is active |
| `invalid_audio_format` | Unsupported sample rate/channel/bit-depth |
| `no_active_session` | Audio sent before `start` |
| `protocol_error` | Invalid frame, oversized control line, or malformed JSON |
| `idle_timeout` | No messages within `server.idle_timeout_seconds` |
| `session_failed` | Provider or text backend failed |
| `internal_error` | Unexpected implementation error |

## Discovery

If enabled, send one of these UDP datagrams to the discovery port:

```text
VOICEBRIDGE_DISCOVER_V1
```

or:

```json
{"type":"discover"}
```

The response is metadata only:

```json
{
  "type":"voicebridge",
  "service":"voice-input-bridge",
  "protocol":1,
  "websocketPort":18766,
  "websocketPath":"/v1/audio",
  "tcpPort":18767,
  "requiresToken":true,
  "providers":["aliyun"]
}
```

Discovery never returns the token or API keys and does not prove that a responder is trustworthy. A client should still use the normal authentication handshake.

## Status endpoints

- `GET /health` — compact liveness and transport state.
- `GET /v1/status` — provider, active/last session metrics, transport state; transcript text is redacted.
- `GET /v1/protocol` — machine-readable protocol constants.

All endpoints are read-only, `no-store`, and available on `http_host:http_port`.

## Compatibility rules for clients

1. Send `hello` and wait for `hello_ack`.
2. Send `start` and wait for `listening` before streaming if practical.
3. Use 20 ms PCM chunks.
4. On `stop`, keep reading until `session_end` or an error.
5. Reconnect and repeat the handshake after a network failure; sessions are not resumable.
6. Do not assume a single final event if a provider can commit multiple sentences.
7. Never send credentials in query strings; query strings often appear in proxy logs.
