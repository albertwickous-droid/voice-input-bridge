from __future__ import annotations

import copy
from typing import Any

from voicebridge import __version__
from voicebridge.config import BridgeConfig
from voicebridge.http_server import HttpStatusServer
from voicebridge.service import VoiceBridgeService
from voicebridge.transports import (
    DiscoveryTransport,
    SerialTransport,
    TcpTransport,
    WebSocketTransport,
)


class BridgeRuntime:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.service = VoiceBridgeService(config)
        self.http = HttpStatusServer(
            config,
            health_provider=self.health_snapshot,
            status_provider=self.public_status_snapshot,
            protocol_provider=self.protocol_info,
        )
        self.websocket = WebSocketTransport(config, self.service)
        self.tcp = TcpTransport(config, self.service)
        self.serial = SerialTransport(config, self.service)
        self.discovery = DiscoveryTransport(config, self.service)
        self._started = False

    async def start(self) -> None:
        if not await self.http.start():
            raise RuntimeError(self.http.status().get("error") or "HTTP server failed to start")
        await self.websocket.start()
        await self.tcp.start()
        await self.serial.start()
        await self.discovery.start()
        self._started = True

    async def close(self) -> None:
        await self.discovery.close()
        await self.serial.close()
        await self.tcp.close()
        await self.websocket.close()
        await self.service.close()
        await self.http.close()
        self._started = False

    def transport_snapshots(self) -> dict[str, dict[str, Any]]:
        return {
            "http": self.http.status(),
            "websocket": self.websocket.status(),
            "tcp": self.tcp.status(),
            "serial": self.serial.status(),
            "discovery": self.discovery.status(),
        }

    def health_snapshot(self) -> dict[str, Any]:
        transports = self.transport_snapshots()
        data_states = {
            transports["websocket"]["state"],
            transports["tcp"]["state"],
            transports["serial"]["state"],
        }
        data_ready = bool(data_states & {"listening", "connected"})
        errors = {
            name: value["error"]
            for name, value in transports.items()
            if value.get("state") == "error" and value.get("error")
        }
        return {
            "ok": transports["http"]["state"] == "listening" and data_ready and not errors,
            "service": "voice-input-bridge",
            "version": __version__,
            "started": self._started,
            "provider": self.config.asr.provider,
            "activeSession": self.service.status_snapshot()["activeSession"] is not None,
            "transports": {
                name: {"state": value["state"], "error": value["error"]}
                for name, value in transports.items()
            },
        }

    def public_status_snapshot(self) -> dict[str, Any]:
        snapshot = copy.deepcopy(self.service.status_snapshot())
        for key in ("activeSession", "lastSession"):
            session = snapshot.get(key)
            if isinstance(session, dict):
                for text_key in ("lastPartial", "lastFinal"):
                    value = session.get(text_key)
                    if value:
                        session[text_key] = {"redacted": True, "characters": len(str(value))}
        snapshot["runtime"] = {
            "started": self._started,
            "transports": self.transport_snapshots(),
        }
        snapshot["tokenConfigured"] = bool(self.config.server.token)
        snapshot["requireToken"] = self.config.server.require_token
        return snapshot

    def protocol_info(self) -> dict[str, Any]:
        return {
            "service": "voice-input-bridge",
            "version": __version__,
            "protocolVersion": 1,
            "audio": {
                "encoding": "pcm_s16le",
                "sampleRates": [8000, 16000, 24000, 48000],
                "channels": [1, 2],
                "frameMagic": "AUD1",
                "frameHeaderBytes": 8,
                "frameLength": "little-endian uint16 payload length",
                "frameSequence": "little-endian uint16 sequence",
            },
            "control": "UTF-8 newline-delimited JSON objects",
            "websocket": {
                "port": self.config.server.ws_port,
                "path": self.config.transports.websocket.path,
            },
            "tcp": {"port": self.config.server.tcp_port},
            "discovery": {
                "port": self.config.server.discovery_port,
                "request": "VOICEBRIDGE_DISCOVER_V1",
            },
            "messages": {
                "client": ["hello", "start", "stop", "ping", "status"],
                "server": [
                    "hello_ack",
                    "listening",
                    "partial",
                    "final",
                    "warning",
                    "error",
                    "stopped",
                    "session_end",
                    "pong",
                ],
            },
        }
