from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(ValueError):
    """Raised when a configuration file is missing required or valid values."""


def _expand_environment(value: Any) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, "" if default is None else default)

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_environment(item) for key, item in value.items()}
    return value


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a TOML table")
    return value


def _int(value: Any, name: str, default: int) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _float(value: Any, name: str, default: float) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number") from exc


def _bool(value: Any, name: str, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{name} must be true or false")


def _str(value: Any, name: str, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be a string")
    return value


def _port(value: Any, name: str, default: int) -> int:
    result = _int(value, name, default)
    if result < 1 or result > 65_535:
        raise ConfigError(f"{name} must be between 1 and 65535")
    return result


@dataclass(frozen=True, slots=True)
class WebSocketTransportConfig:
    enabled: bool = True
    path: str = "/v1/audio"


@dataclass(frozen=True, slots=True)
class TcpTransportConfig:
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class SerialTransportConfig:
    enabled: bool = False
    port: str = "auto"
    baudrate: int = 115_200


@dataclass(frozen=True, slots=True)
class DiscoveryTransportConfig:
    enabled: bool = False


@dataclass(frozen=True, slots=True)
class TransportConfig:
    websocket: WebSocketTransportConfig = field(default_factory=WebSocketTransportConfig)
    tcp: TcpTransportConfig = field(default_factory=TcpTransportConfig)
    serial: SerialTransportConfig = field(default_factory=SerialTransportConfig)
    discovery: DiscoveryTransportConfig = field(default_factory=DiscoveryTransportConfig)


@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    http_host: str = "127.0.0.1"
    http_port: int = 18_765
    ws_port: int = 18_766
    tcp_port: int = 18_767
    discovery_port: int = 18_768
    token: str = ""
    require_token: bool = False
    max_audio_seconds: float = 120.0
    idle_timeout_seconds: float = 60.0

    @property
    def network_exposed(self) -> bool:
        return self.host not in {"127.0.0.1", "::1", "localhost"}


@dataclass(frozen=True, slots=True)
class ASRConfig:
    provider: str = "mock"
    language: str = "zh-CN"
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InputConfig:
    backend: str = "auto"
    send_partial: bool = True
    final_suffix: str = ""
    require_same_window: bool = True
    paste_shortcut: str = "auto"


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    level: str = "INFO"
    json: bool = False


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    transports: TransportConfig = field(default_factory=TransportConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    input: InputConfig = field(default_factory=InputConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    source_path: Path | None = None

    def validate(self) -> list[str]:
        warnings: list[str] = []
        if not self.server.host or not self.server.http_host:
            raise ConfigError("server host values cannot be empty")
        if not self.transports.websocket.path.startswith("/") or any(
            char.isspace() for char in self.transports.websocket.path
        ):
            raise ConfigError("transports.websocket.path must start with / and contain no spaces")
        if self.transports.serial.baudrate <= 0:
            raise ConfigError("transports.serial.baudrate must be greater than zero")
        if not math.isfinite(self.server.max_audio_seconds) or self.server.max_audio_seconds <= 0:
            raise ConfigError("server.max_audio_seconds must be a finite positive number")
        if (
            not math.isfinite(self.server.idle_timeout_seconds)
            or self.server.idle_timeout_seconds <= 0
        ):
            raise ConfigError("server.idle_timeout_seconds must be a finite positive number")
        ports = [self.server.http_port, self.server.ws_port, self.server.tcp_port]
        if self.transports.discovery.enabled:
            ports.append(self.server.discovery_port)
        if len(set(ports)) != len(ports):
            raise ConfigError("enabled transport ports must be different")
        if self.server.network_exposed and not self.server.token:
            warnings.append(
                "server.host is not loopback but server.token is empty; LAN clients are unauthenticated"
            )
        if self.server.network_exposed and not self.server.require_token:
            warnings.append(
                "server.require_token is false while listening on a network interface"
            )
        if self.server.require_token and not self.server.token:
            warnings.append(
                "server.require_token is true but server.token is empty; all clients will be rejected"
            )
        if self.server.token and not self.server.require_token:
            warnings.append("server.token is configured but require_token is false")
        if not any(
            (
                self.transports.websocket.enabled,
                self.transports.tcp.enabled,
                self.transports.serial.enabled,
            )
        ):
            warnings.append("all data transports are disabled")
        if self.input.backend not in {
            "auto",
            "windows",
            "macos",
            "clipboard",
            "stdout",
            "null",
        }:
            warnings.append(f"unknown built-in input backend: {self.input.backend}")
        return warnings


def _default_path() -> Path | None:
    configured = os.environ.get("VOICEBRIDGE_CONFIG", "").strip()
    if configured:
        return Path(configured).expanduser()
    candidate = Path.cwd() / "config.toml"
    return candidate if candidate.exists() else None


def load_config(path: str | Path | None = None) -> BridgeConfig:
    config_path = Path(path).expanduser() if path else _default_path()
    raw: dict[str, Any] = {}
    if config_path is not None:
        if not config_path.exists():
            raise ConfigError(f"configuration file not found: {config_path}")
        try:
            raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"could not read {config_path}: {exc}") from exc
        raw = _expand_environment(raw)

    server = _mapping(raw.get("server"), "server")
    transports = _mapping(raw.get("transports"), "transports")
    websocket = _mapping(transports.get("websocket"), "transports.websocket")
    tcp = _mapping(transports.get("tcp"), "transports.tcp")
    serial = _mapping(transports.get("serial"), "transports.serial")
    discovery = _mapping(transports.get("discovery"), "transports.discovery")
    asr = _mapping(raw.get("asr"), "asr")
    input_table = _mapping(raw.get("input"), "input")
    logging_table = _mapping(raw.get("logging"), "logging")

    provider = _str(asr.get("provider"), "asr.provider", "mock").strip().lower()
    provider_options = _mapping(asr.get(provider), f"asr.{provider}")
    common_options = _mapping(asr.get("options"), "asr.options")
    options = {**common_options, **provider_options}

    result = BridgeConfig(
        server=ServerConfig(
            host=_str(server.get("host"), "server.host", "127.0.0.1"),
            http_host=_str(server.get("http_host"), "server.http_host", "127.0.0.1"),
            http_port=_port(server.get("http_port"), "server.http_port", 18_765),
            ws_port=_port(server.get("ws_port"), "server.ws_port", 18_766),
            tcp_port=_port(server.get("tcp_port"), "server.tcp_port", 18_767),
            discovery_port=_port(
                server.get("discovery_port"), "server.discovery_port", 18_768
            ),
            token=_str(server.get("token"), "server.token", "").strip(),
            require_token=_bool(
                server.get("require_token"), "server.require_token", False
            ),
            max_audio_seconds=_float(
                server.get("max_audio_seconds"), "server.max_audio_seconds", 120.0
            ),
            idle_timeout_seconds=_float(
                server.get("idle_timeout_seconds"),
                "server.idle_timeout_seconds",
                60.0,
            ),
        ),
        transports=TransportConfig(
            websocket=WebSocketTransportConfig(
                enabled=_bool(
                    websocket.get("enabled"), "transports.websocket.enabled", True
                ),
                path=_str(
                    websocket.get("path"), "transports.websocket.path", "/v1/audio"
                ),
            ),
            tcp=TcpTransportConfig(
                enabled=_bool(tcp.get("enabled"), "transports.tcp.enabled", True)
            ),
            serial=SerialTransportConfig(
                enabled=_bool(
                    serial.get("enabled"), "transports.serial.enabled", False
                ),
                port=_str(serial.get("port"), "transports.serial.port", "auto"),
                baudrate=_int(
                    serial.get("baudrate"), "transports.serial.baudrate", 115_200
                ),
            ),
            discovery=DiscoveryTransportConfig(
                enabled=_bool(
                    discovery.get("enabled"), "transports.discovery.enabled", False
                )
            ),
        ),
        asr=ASRConfig(
            provider=provider,
            language=_str(asr.get("language"), "asr.language", "zh-CN"),
            options=options,
        ),
        input=InputConfig(
            backend=_str(input_table.get("backend"), "input.backend", "auto").lower(),
            send_partial=_bool(
                input_table.get("send_partial"), "input.send_partial", True
            ),
            final_suffix=_str(
                input_table.get("final_suffix"), "input.final_suffix", ""
            ),
            require_same_window=_bool(
                input_table.get("require_same_window"),
                "input.require_same_window",
                True,
            ),
            paste_shortcut=_str(
                input_table.get("paste_shortcut"), "input.paste_shortcut", "auto"
            ),
        ),
        logging=LoggingConfig(
            level=_str(logging_table.get("level"), "logging.level", "INFO").upper(),
            json=_bool(logging_table.get("json"), "logging.json", False),
        ),
        source_path=config_path,
    )
    result.validate()
    return result
