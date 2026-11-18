from __future__ import annotations

import asyncio
import json
from typing import Any

from voicebridge.config import BridgeConfig
from voicebridge.service import VoiceBridgeService

_DISCOVER_TEXT = b"VOICEBRIDGE_DISCOVER_V1"


class DiscoveryTransport:
    name = "discovery"

    def __init__(self, config: BridgeConfig, service: VoiceBridgeService) -> None:
        self.config = config
        self.service = service
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: asyncio.DatagramProtocol | None = None
        self._state = "stopped"
        self._error: str | None = None

    async def start(self) -> bool:
        if not self.config.transports.discovery.enabled:
            self._state = "disabled"
            return True
        loop = asyncio.get_running_loop()
        transport_holder: dict[str, Any] = {}

        class Protocol(asyncio.DatagramProtocol):
            def connection_made(inner_self, transport: asyncio.DatagramTransport) -> None:
                transport_holder["transport"] = transport

            def datagram_received(
                inner_self, data: bytes, address: tuple[str, int]
            ) -> None:
                if not self._is_discovery_request(data):
                    return
                transport = transport_holder.get("transport")
                if transport is None:
                    return
                payload = {
                    "type": "voicebridge",
                    "service": "voice-input-bridge",
                    "protocol": 1,
                    "websocketPort": self.config.server.ws_port,
                    "websocketPath": self.config.transports.websocket.path,
                    "tcpPort": self.config.server.tcp_port,
                    "requiresToken": self.config.server.require_token,
                    "providers": [self.config.asr.provider],
                }
                encoded = json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                transport.sendto(encoded, address)

        try:
            transport, protocol = await loop.create_datagram_endpoint(
                Protocol,
                local_addr=(self.config.server.host, self.config.server.discovery_port),
            )
        except Exception as exc:
            self._state = "error"
            self._error = f"{exc.__class__.__name__}: {exc}"
            return False
        self._transport = transport
        self._protocol = protocol
        self._state = "listening"
        self._error = None
        return True

    @staticmethod
    def _is_discovery_request(data: bytes) -> bool:
        if data.strip() == _DISCOVER_TEXT:
            return True
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        return isinstance(value, dict) and value.get("type") == "discover"

    async def close(self) -> None:
        transport, self._transport = self._transport, None
        if transport is not None:
            transport.close()
        self._protocol = None
        self._state = "stopped"

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.config.transports.discovery.enabled,
            "state": self._state,
            "host": self.config.server.host,
            "port": self.config.server.discovery_port,
            "error": self._error,
        }
