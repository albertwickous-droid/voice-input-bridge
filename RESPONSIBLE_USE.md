# Responsible use

Voice Input Bridge is intended for authorized dictation, accessibility, device prototyping, and workflow integration.

## Allowed scope

Use the project only when you have permission to:

- capture the audio;
- operate the device and network;
- use the cloud ASR or local model;
- inject text into the target application and account; and
- process any transcript or related data.

## Do not use it to bypass controls

Do not use the project to bypass authentication, authorization, CAPTCHAs, rate limits, access controls, monitoring, or application security boundaries. Do not use it for covert surveillance, credential collection, harassment, or unauthorized command execution.

## Protect people and data

- Obtain consent before recording other people where required.
- Do not send confidential meetings, customer data, credentials, or regulated data to a cloud provider without an approved data-processing basis.
- Do not commit real audio, transcripts, API keys, tokens, Wi-Fi passwords, or device identifiers.
- Review provider retention, region, training, and billing terms before use.

## Keep the deployment bounded

- Keep the default loopback listener unless network access is required.
- A static token authenticates clients but does not encrypt traffic.
- Use a trusted LAN, VPN, SSH tunnel, or TLS reverse proxy for remote access.
- Restrict firewall ingress to known devices and ports.
- Run provider plugins and command-line ASR only from reviewed sources.

## Review generated text

ASR output can be inaccurate even when the provider reports a final result. Review text before sending messages, executing commands, submitting forms, or making decisions.

## Report problems safely

Report vulnerabilities through the repository's private GitHub Security Advisory flow. Do not publish working exploits, real credentials, or personal audio in a public issue.
