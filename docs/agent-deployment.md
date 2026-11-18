# Agent Deployment

If you are an agent, follow these steps exactly. Stop and report when a prerequisite, permission, or safety boundary is missing.

## Scope

`voice-input-bridge` is a Python audio-to-text bridge. A device sends PCM audio over WebSocket, TCP, or serial; the bridge calls an ASR provider and injects partial/final text into the foreground Windows or macOS application.

Supported production targets:

- Windows for `SendInput` text injection.
- macOS for Quartz text injection, subject to Accessibility permission.
- Linux for the core, transport, stdout, and clipboard paths; do not claim native Linux text injection without a dedicated backend.

## Prerequisites

- Python 3.10 or newer.
- A checkout of this repository.
- Permission to create a local virtual environment.
- For cloud ASR: a provider account and an API key supplied by the user through the environment. Read `docs/providers.md` first: only `aliyun`, `deepgram`, `mock`, and `command` are built in, and other vendors require a provider plugin or a command adapter.
- For real text injection: explicit user authorization for the target application and foreground window.

## Read-only preflight

Run these commands first and report the output before changing anything:

```powershell
git status --short --branch
git remote -v
python --version
python -m pip --version
Test-Path config.demo.toml
Test-Path config.example.toml
```

Do not inspect or copy secrets, browser cookies, credential stores, private recordings, or unrelated workspace projects.

## Install

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

On macOS or Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Do not install optional provider extras unless the user requested that provider.

## Configure

Start from the safe demo configuration:

```powershell
voicebridge doctor --config config.demo.toml
```

The demo uses the deterministic `mock` provider and the `null` input backend. It must not type into the foreground window.

For a real deployment, copy `config.example.toml` to `config.toml` and edit it locally. Keep `config.toml`, API keys, device passwords, tokens, and Wi-Fi credentials out of Git. Prefer environment variables such as `DASHSCOPE_API_KEY` or `DEEPGRAM_API_KEY`.

## Validate

Use the smallest relevant verification sequence first:

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python scripts/smoke_test.py
```

If the release owner has explicitly requested packaging validation, also run:

```powershell
python -m build --no-isolation
python -m twine check dist/*
```

Do not start a cloud provider or real microphone session merely to make a test pass.

## Expected evidence

Successful local validation produces:

- `pytest`: exit code `0`, with the current test count printed.
- Smoke test: `Smoke test passed: final, hello_ack, listening, partial, session_end`.
- `doctor`: exit code `0` for the demo configuration, unless a documented dependency or port is unavailable.
- A running service should answer `/health` with HTTP `200` and `ok: true`.
- Release artifacts, when requested: `dist/*.whl` and `dist/*.tar.gz`.
- No raw API key, Wi-Fi password, token, personal path, or recording should appear in output or files.

## Cleanup

- Stop only services started by this run.
- Leave the user's existing services and unrelated ports untouched.
- Remove only temporary files created by this run.
- Do not delete the repository, virtual environment, recordings, credentials, or another task's output without explicit permission.

## Failure handling

Retry only transient network or package-index failures. Stop and report immediately when any of these occur:

- A required credential is missing.
- A port is occupied by an unknown service.
- `SendInput` or Quartz reports a permission failure.
- A cloud provider returns authentication, quota, or billing errors.
- The foreground window changes during injection.
- Tests fail because of application code rather than a temporary dependency download.
- A command would push, publish, tag, sign, or expose a repository.

## Never do this

- Do not commit or print API keys, tokens, cookies, passwords, private keys, or `.env` contents.
- Do not upload real audio, chat content, device identifiers, or personal data as test fixtures.
- Do not kill the user's existing bridge or unrelated services on ports `8765`/`8766`.
- Do not type into an unrelated foreground window to test injection.
- Do not bypass permissions, CAPTCHAs, access controls, or device authorization.
- Do not create a GitHub remote, push commits, make a repository public, create a tag, or publish a Release without explicit project-specific authorization.
- Do not claim that macOS Quartz, every serial device, or every cloud provider has been verified when it has not.

## Release checklist

Before handing the repository to a human reviewer:

- Confirm the project owner, repository name, visibility, and license.
- Re-run the commands above in a clean checkout or worktree.
- Check Markdown relative links and images.
- Review `git diff --cached --stat`, `git diff --cached --check`, and `git ls-files`.
- Run the secret and private-path audit from the workspace publishing guide.
- Report which checks ran on the current working tree and which ran on a clean clone.
