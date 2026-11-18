from __future__ import annotations

import socket

from voicebridge.config import (
    ASRConfig,
    BridgeConfig,
    DiscoveryTransportConfig,
    InputConfig,
    LoggingConfig,
    SerialTransportConfig,
    ServerConfig,
    TcpTransportConfig,
    TransportConfig,
    WebSocketTransportConfig,
)


def free_tcp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def make_config(
    *,
    http_port: int | None = None,
    ws_port: int | None = None,
    tcp_port: int | None = None,
    discovery_port: int | None = None,
    websocket: bool = True,
    tcp: bool = True,
    serial: bool = False,
    discovery: bool = False,
    provider: str = "mock",
    options: dict[str, object] | None = None,
    backend: str = "null",
    require_token: bool = False,
    token: str = "",
    max_audio_seconds: float = 120.0,
) -> BridgeConfig:
    ports = {
        http_port or free_tcp_port(),
        ws_port or free_tcp_port(),
        tcp_port or free_tcp_port(),
    }
    while len(ports) < 3:
        ports.add(free_tcp_port())
    http_port, ws_port, tcp_port = list(ports)
    if discovery_port is None:
        discovery_port = free_udp_port()
    return BridgeConfig(
        server=ServerConfig(
            host="127.0.0.1",
            http_host="127.0.0.1",
            http_port=http_port,
            ws_port=ws_port,
            tcp_port=tcp_port,
            discovery_port=discovery_port,
            token=token,
            require_token=require_token,
            max_audio_seconds=max_audio_seconds,
            idle_timeout_seconds=10,
        ),
        transports=TransportConfig(
            websocket=WebSocketTransportConfig(enabled=websocket, path="/v1/audio"),
            tcp=TcpTransportConfig(enabled=tcp),
            serial=SerialTransportConfig(enabled=serial),
            discovery=DiscoveryTransportConfig(enabled=discovery),
        ),
        asr=ASRConfig(
            provider=provider,
            language="zh-CN",
            options={
                "transcript": "你好，世界。",
                "partial_words": ["你好", "你好世界"],
                **(options or {}),
            }
            if provider == "mock"
            else (options or {}),
        ),
        input=InputConfig(backend=backend, send_partial=True),
        logging=LoggingConfig(level="WARNING"),
    )
