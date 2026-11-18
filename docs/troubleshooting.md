# Troubleshooting

## First checks

```bash
voicebridge doctor --config config.toml --json
curl http://127.0.0.1:18765/health
curl http://127.0.0.1:18765/v1/status
```

`doctor` never prints a token or API key. It reports only configured/not configured. If the service is already running, port checks may correctly report the ports as unavailable; stop it before running a fresh preflight.

## The service starts but no text appears

Check the separation of layers:

1. **Transport:** Did `/health` show WebSocket/TCP/listening and a connected client?
2. **ASR:** Did the client receive `partial` or `final` events?
3. **Text input:** Did the foreground application receive the final text?

If there are final events but no typed text, the problem is the input backend, not the network or cloud ASR.

Common causes:

- `input.backend = "null"` in `config.demo.toml` — this is intentional for the safe demo.
- The foreground window changed and `require_same_window = true`.
- The target app runs at a higher Windows integrity level.
- macOS Accessibility permission is missing.
- A Text Services/IME control does not accept synthetic Unicode; test in Notepad, a browser input, and a terminal separately.
- Security software blocked `SendInput`/Quartz.

## The microphone is not the default device

The bridge does not open the host microphone for device clients. The ESP32/phone/browser captures audio and sends it. Select the correct microphone in the client:

- Browser: browser microphone permission chooser.
- Python example: `sounddevice` default device, or change your OS input device.
- ESP32/M5: configure the board microphone pins/API.

For a host-only test, use a WAV captured from the correct device:

```bash
voicebridge serve --config config.toml
python examples/clients/python_client.py --target ws://127.0.0.1:18766/v1/audio --wav test.wav --no-realtime
```

The WAV must be mono, 16 kHz, 16-bit PCM.

## Text appears only after I stop speaking

This is expected when:

- The provider is `command` (WAV is buffered until `stop`).
- `asr.*.interim_results` is disabled.
- `input.send_partial = false`.
- The ASR provider does not return partial results for the selected model/language.
- The browser client or device sends one huge frame only at the end.

For cloud streaming:

```toml
[input]
send_partial = true
```

and send 20 ms `AUD1` frames continuously rather than collecting the whole utterance.

## Real-time results arrive too slowly

Measure the layers separately:

1. Frame cadence: 20 ms chunks should arrive continuously.
2. Network RTT from the device to the PC.
3. PC-to-provider latency and provider region.
4. `firstPartialMs` in `session_end`.
5. Text injection time.

Optimizations:

- Use the provider region nearest to the bridge host.
- Keep server and device on the same LAN.
- Disable Wi-Fi power save on the ESP32 only if testing shows it helps.
- Avoid sending giant WebSocket messages.
- Do not run a large local model on a memory-constrained machine.
- Use a provider/model that supports native streaming interim results.

Accuracy and latency are separate problems. A fast, garbled final still means the ASR path is working but the audio or model is unsuitable.

## Garbled Chinese recognition

Check in this order:

1. Use 16 kHz mono S16LE, not 8 kHz or stereo bytes mislabeled as mono.
2. Verify microphone gain; clipping and very low level both hurt accuracy.
3. Confirm language hints, for example `["zh", "en"]`.
4. Use an ASR vocabulary/hotword list for names and domain terms.
5. Compare the same WAV through the provider console and through the bridge.
6. Test a different model/provider before changing the transport.

On ESP32/M5, verify the actual microphone sample rate and channel mask. A correctly connected microphone with an I2S format mismatch can produce noise that looks like a transport failure.

## WebSocket fails from another machine

- Set `server.host = "0.0.0.0"` to listen on LAN interfaces; loopback is not reachable remotely.
- Allow the TCP port in Windows Defender Firewall/macOS firewall.
- Use the PC's LAN IP, not `127.0.0.1`, in the device.
- If `require_token = true`, configure the same token on the device.
- If the page is HTTPS, use `wss://`.
- Do not expose an unencrypted token listener directly to the public internet.

The HTTP status server uses `http_host`; WebSocket/TCP use `server.host`.

## Browser microphone does not open

Open the page through `http://127.0.0.1:8000` or HTTPS, not `file://`. Browsers restrict microphone access outside secure contexts. Check the browser permission prompt and site settings. A page loaded over HTTPS cannot connect to an unencrypted `ws://` endpoint due to mixed-content rules; use a TLS reverse proxy and `wss://`.

## ESP32 cannot connect to Wi-Fi

- Most ESP32 boards support only 2.4 GHz Wi-Fi.
- Verify the SSID is the 2.4 GHz network, not a 5 GHz network with a similar name.
- Print `WiFi.localIP()` and confirm it is in the same subnet as the bridge.
- Check firewall rules for inbound connections to the bridge.
- Use a private build-time header for SSID/password/token if the repository is public.

## USB serial device is not detected

- Install the serial extra: `pip install "voice-input-bridge[serial]"`.
- Set `transports.serial.enabled = true`.
- Prefer an explicit port such as `COM5` or `/dev/cu.usbmodem...` when auto-detection is ambiguous.
- Confirm the device appears as a USB CDC/ACM port.
- Avoid opening the same port in the Arduino Serial Monitor while the bridge is connected.
- After a reconnect, send `hello` and `start` again; sessions are not resumed.

## Port already in use

Change all enabled transport ports to distinct free values. HTTP, WebSocket, TCP, and discovery cannot share a port in this service. On Windows:

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object LocalPort -in 18765,18766,18767
```

## macOS has no output

Grant Accessibility permission to the exact interpreter or application that runs the service. If you launch from Terminal, the Terminal application may need permission; if you use a venv, the resolved Python binary may be the one recorded by macOS. Restart the service after changing privacy permissions.

## Need more diagnostics without leaking secrets

- `/health` contains transport state but no token/key.
- `/v1/status` redacts transcript text.
- Provider errors are intentionally truncated.
- Do not enable verbose packet dumps in a public issue.
- Do not paste real API keys into logs, YAML, TOML, chat, or screenshots.

If a provider error remains unclear, reproduce with `mock`, capture the protocol event sequence, and report only sanitized fields.

## Diagnosing ASR quality separately from transport quality

Use a deterministic WAV and inspect the events:

```bash
voicebridge simulate --target ws://127.0.0.1:18766/v1/audio --seconds 1
```

For a real provider, compare:

- `frames` and `bytesReceived` in `session_end`;
- `droppedBytes`;
- `firstPartialMs`;
- whether a `final` event exists;
- the final text itself.

If frames arrive and `droppedBytes` is zero but the final text is wrong, fix the audio/model/hotwords. If frames do not arrive, fix the device/transport first.
