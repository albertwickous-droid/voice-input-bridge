# Security policy

## Supported versions

The project is alpha. Security fixes are applied to the latest release on the `main` branch. There is no long-term support guarantee yet.

## Report a vulnerability

Do not open a public issue for a suspected vulnerability involving credential disclosure, arbitrary command execution, unsafe network exposure, or text injection into an unintended application.

Report privately through the repository's **Security advisories -> Report a vulnerability** flow. Include:

- affected version/commit;
- platform and Python version;
- a minimal reproduction using `mock` or sanitized fixtures;
- whether a token, API key, transcript, or local file was exposed;
- suggested remediation if known.

Do not include real API keys, Wi-Fi credentials, personal audio, or full transcript contents.

## Threat model

Voice Input Bridge handles:

- raw microphone audio;
- cloud provider credentials;
- a client authentication token;
- mutable foreground text;
- optional serial devices;
- temporary WAV files for command-line ASR.

The primary deployment assumption is a trusted local machine plus a trusted LAN/VPN. Loopback-only is the default.

## Network exposure

- `server.host` defaults to `127.0.0.1`.
- A static token is authentication, not encryption.
- WebSocket/TCP/serial traffic is not TLS by itself.
- If network exposure is required, put the service behind WireGuard/Tailscale, an SSH tunnel, or a TLS reverse proxy.
- Restrict firewall ingress to known device addresses and ports.
- Do not publish HTTP/status endpoints directly to the public internet.
- Change the default token when `require_token = true`; an empty token with `require_token = true` rejects all clients.

## Secrets

- The core never automatically reads `.env`; this makes secret loading explicit.
- Use environment variables or a secret manager to populate `${VAR}` values.
- Never commit `config.toml`, `.env`, provider keys, Wi-Fi passwords, DPAPI credential blobs, or device tokens.
- Never paste a key into an issue, screenshot, or chat.
- `voicebridge config` redacts secret-like string keys. `doctor` reports configured/not configured only.
- HTTP `/health` and `/v1/status` never return the token or provider API keys.
- Provider error messages are truncated but may contain upstream request identifiers; review before posting publicly.

## Audio and transcript privacy

- The core does not persist audio.
- `command` creates a temporary WAV because local ASR commands need a file; it is removed when the command returns.
- Cloud providers receive audio at their endpoint. Review the provider's retention, region, and data-processing terms.
- `/v1/status` redacts transcript text. Authenticated protocol clients can receive transcript events by design.
- `stdout` and `null` sinks are useful for safe tests; `stdout` may expose transcript text to terminal logs.

## Text injection risks

`SendInput`/Quartz types into the foreground application. The bridge records the target window/application at session start and pauses if it changes when `require_same_window = true`. Keep this guard enabled unless you deliberately need global injection.

- Never run an untrusted provider plugin in a privileged desktop session.
- A malicious plugin runs as the bridge process and can access audio, credentials, and local files.
- Pin and review third-party provider packages.
- Clipboard fallback may overwrite the user's clipboard and may expose text to clipboard history tools.

## Command provider

The command provider uses `subprocess.run` without a shell and expands only documented placeholders. It still executes the configured executable with the bridge user's permissions. Configure only trusted binaries and model files. Do not accept command options directly from unauthenticated network clients.

## Dependency and supply-chain hygiene

Before release:

```bash
python -m pip install -e ".[dev,all]"
ruff check .
pytest -q
python -m build
twine check dist/*
```

Also review dependency advisories and lock/model versions. Exact-version OSV checks at the 2026-11-18 snapshot found no known advisories for the primary versions listed in `docs/providers.md`, but this is not a guarantee. Re-run checks at release time.

## Disclosure timeline

We aim to acknowledge a report within 7 days, provide a remediation plan when practical, and coordinate disclosure after a fix is available. The project is maintained on a best-effort basis.
