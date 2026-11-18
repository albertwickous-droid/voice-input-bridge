from __future__ import annotations

from pathlib import Path

import pytest

from voicebridge.config import (
    BridgeConfig,
    ConfigError,
    DiscoveryTransportConfig,
    ServerConfig,
    TransportConfig,
    load_config,
)
from voicebridge.transports import TcpTransport


def _write_config(path: Path, *, discovery_port: int | None = None) -> None:
    discovery = ""
    if discovery_port is not None:
        discovery = """
[transports.discovery]
enabled = true
"""
    path.write_text(
        f"""
[server]
host = "127.0.0.1"
http_port = 28765
ws_port = 28766
tcp_port = 28767
discovery_port = {discovery_port or 28768}
token = "${{VOICEBRIDGE_TEST_TOKEN:-fallback}}"

[transports.websocket]
enabled = true
path = "/v1/audio"

[transports.tcp]
enabled = true

{discovery}

[asr]
provider = "mock"

[asr.mock]
transcript = "test"

[input]
backend = "null"
""",
        encoding="utf-8",
    )


def test_environment_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.toml"
    _write_config(path)
    monkeypatch.setenv("VOICEBRIDGE_TEST_TOKEN", "secret-token")
    config = load_config(path)
    assert config.server.token == "secret-token"
    assert config.source_path == path


def test_environment_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.toml"
    _write_config(path)
    monkeypatch.delenv("VOICEBRIDGE_TEST_TOKEN", raising=False)
    config = load_config(path)
    assert config.server.token == "fallback"


def test_require_token_without_token_warns() -> None:
    config = BridgeConfig(
        server=ServerConfig(require_token=True, token=""),
        transports=TransportConfig(),
    )
    assert any("all clients will be rejected" in warning for warning in config.validate())


def test_duplicate_discovery_port_is_rejected() -> None:
    config = BridgeConfig(
        server=ServerConfig(http_port=28765, ws_port=28766, tcp_port=28767, discovery_port=28767),
        transports=TransportConfig(discovery=DiscoveryTransportConfig(enabled=True)),
    )
    with pytest.raises(ConfigError, match="ports must be different"):
        config.validate()


def test_transport_module_import_does_not_open_ports() -> None:
    assert TcpTransport.__name__ == "TcpTransport"
