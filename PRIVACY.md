# Privacy

Voice Input Bridge is a local bridge process. The repository does not include analytics, telemetry, advertising SDKs, or a project-operated cloud backend.

## Data processed by the bridge

The process may handle:

- raw PCM audio received from a device or client;
- transcript events, including partial and final text;
- provider credentials and an optional client token;
- foreground-window metadata used by the injection guard;
- diagnostic status, counters, and redacted logs; and
- temporary WAV files for the `command` provider.

The core does not intentionally persist audio after a session. The `command` provider creates a temporary WAV because command-line ASR tools normally require a file; it is removed when the command returns. The operating system, filesystem, antivirus, crash reporter, or another process may retain copies outside the project's control.

## Cloud ASR

When a cloud provider is selected, audio and related metadata are sent to that provider's endpoint. The provider's own privacy policy, retention rules, region, account terms, and billing terms apply. Voice Input Bridge does not control those systems.

The default providers in this repository are client integrations; they do not add a separate project-operated relay.

## Logs and diagnostics

- `/health` and `/v1/status` are designed to avoid returning tokens, provider keys, or transcript text.
- Protocol clients receive transcript events by design.
- `stdout` can expose transcript text in terminal logs. Use `null` or sanitized fixtures for public CI and screenshots.
- Provider errors may include upstream request identifiers. Review logs before sharing them.

## Clipboard and input history

Clipboard fallback may overwrite the clipboard and may be captured by clipboard-history tools. Windows/macOS input APIs may also be observed by accessibility, security, or productivity software. Review those tools before handling sensitive text.

## User responsibilities

You are responsible for obtaining consent, choosing an appropriate provider and region, configuring retention, protecting credentials, and complying with applicable privacy and data-protection law.

## Contact

Do not post personal data, real recordings, credentials, or private transcripts in a public issue. Use the repository's private Security Advisory flow for security or credential exposure reports.
