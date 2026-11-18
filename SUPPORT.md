# Support

Voice Input Bridge is an alpha project maintained on a best-effort basis. There is no guaranteed response time or long-term support commitment.

## Before opening an issue

1. Run `voicebridge doctor --config config.demo.toml`.
2. Run `python scripts/smoke_test.py` with the built-in `mock` provider.
3. Read [docs/troubleshooting.md](docs/troubleshooting.md).
4. Check whether the provider is actually built in; see [docs/providers.md](docs/providers.md).
5. Reproduce with the smallest possible config and redact secrets, paths, device IDs, and transcript text.

## Include in a bug report

- version or commit;
- operating system and Python version;
- device/transport and provider names;
- the command that failed;
- the expected and actual behavior;
- sanitized logs or event traces; and
- whether the problem is transport, ASR quality, text injection, packaging, or documentation.

## Do not post

- API keys, tokens, cookies, passwords, private keys, or Wi-Fi credentials;
- real audio, personal transcripts, customer data, private IP addresses, or device serial numbers;
- working exploit details in a public issue; or
- unredacted screenshots of terminals, configuration files, or provider consoles.

Report vulnerabilities through the repository's private GitHub Security Advisory flow. See [SECURITY.md](SECURITY.md).

## Scope boundaries

The project cannot provide provider-account support, guarantee a particular recognition accuracy, make a cloud service available in every region, or validate every application's text-input behavior. Those limitations are documented in [README.md](README.md) and [DISCLAIMER.md](DISCLAIMER.md).
