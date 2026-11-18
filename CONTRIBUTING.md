# Contributing

Thanks for helping make device-agnostic dictation safer and easier to deploy.

## Development setup

```bash
git clone https://github.com/YOUR_GITHUB_USER/voice-input-bridge.git
cd voice-input-bridge
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
ruff check .
pytest -q
```

Install optional transports/providers when touching them:

```bash
python -m pip install -e ".[dev,all]"
```

Do not run paid ASR tests in the default suite. Use `mock`, captured sanitized fixtures, and fake WebSocket/session objects.

## Coding guidelines

- Support Python 3.10 through 3.12 in the current release line.
- Keep the core free of provider-specific assumptions.
- Keep transport, ASR, input, and CLI boundaries separate.
- Do not print or log raw audio, tokens, API keys, or full provider payloads.
- Bound queues and buffers; add backpressure/drop metrics for streaming paths.
- Isolate per-connection failures so one client cannot terminate a listener.
- Prefer standard library solutions when they are clear and sufficient.
- Add type hints and focused tests for new behavior.
- Use UTF-8 no BOM and LF line endings.

## Adding a provider

A provider package should depend on `voice-input-bridge`, subclass `ASRProvider`, and register an entry point:

```toml
[project.entry-points."voicebridge.providers"]
my_asr = "my_package.provider:MyASRProvider"
```

Document:

- partial/final semantics;
- supported sample rates, channels, and encoding;
- required credentials and region/workspace options;
- audio retention and network destinations;
- timeout and reconnection behavior;
- known limits and provider model names.

Use `ProviderUnavailable` for missing credentials/dependencies and `ProviderError` for upstream failure. Do not raise a raw network exception through the service.

## Adding a transport

Use `StreamDecoder` so the wire contract stays identical. Instantiate one `ConnectionSession` per peer, serialize outbound writes, close the session on disconnect, and add an end-to-end test with `mock` + `null`.

## Testing checklist

- `pytest -q`
- `ruff check .`
- `python -m compileall -q src tests`
- WebSocket + TCP end-to-end with `mock`
- HTTP status redacts transcript text
- token success and rejection
- partial common-prefix edit
- max-audio bound and dropped-byte accounting
- command-provider encoding behavior on Windows
- platform-specific input tests skipped on other platforms

For hardware changes, include a redacted event trace and board pins/firmware version. Do not include Wi-Fi passwords or provider keys.

## Pull requests

- Keep changes focused.
- Explain the user-visible behavior and failure modes.
- Add tests and documentation.
- Do not commit build artifacts, virtual environments, logs, WAVs, or secrets.
- Mention any provider API contract that is based on an external service and cannot be covered by the default test suite.

## Release checks

```bash
python -m build
twine check dist/*
python -m pip install --force-reinstall dist/*.whl
voicebridge --version
voicebridge doctor --config config.demo.toml --json
```

CI runs on Windows, macOS, and Linux for the supported Python versions. A release should also include a clean-environment WebSocket/TCP smoke test and a review of provider/dependency advisories.

## Security

See `SECURITY.md`. Do not disclose credential or injection vulnerabilities in a public issue before coordinated remediation.
