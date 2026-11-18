from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any
from urllib.parse import urlsplit

from voicebridge.config import BridgeConfig
from voicebridge.connection import ConnectionRejected, ConnectionSession
from voicebridge.protocol import ProtocolError, StreamDecoder
from voicebridge.service import VoiceBridgeService


class WebSocketTransport:
    name = "websocket"

    def __init__(self, config: BridgeConfig, service: VoiceBridgeService) -> None:
        self.config = config
        self.service = service
        self._server: Any = None
        self._clients: set[Any] = set()
        self._state = "stopped"
        self._error: str | None = None

    async def start(self) -> bool:
        if not self.config.transports.websocket.enabled:
            self._state = "disabled"
            return True
        try:
            from websockets.asyncio.server import serve
        except ImportError:
            self._state = "error"
            self._error = "websockets dependency is not installed"
            return False
        try:
            self._server = await serve(
                self._handle_client,
                self.config.server.host,
                self.config.server.ws_port,
                max_size=1024 * 1024,
                ping_interval=20,
                ping_timeout=20,
            )
        except Exception as exc:
            self._state = "error"
            self._error = f"{exc.__class__.__name__}: {exc}"
            return False
        self._state = "listening"
        self._error = None
        return True

    async def _handle_client(self, websocket: Any, path: str | None = None) -> None:
        self._clients.add(websocket)
        send_lock = asyncio.Lock()

        async def send_json(message: dict[str, Any]) -> None:
            payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
            async with send_lock:
                await websocket.send(payload)

        connection = ConnectionSession(self.service, send_json)
        decoder = StreamDecoder(strict=True)
        close_code = 1000
        close_reason = "normal closure"
        try:
            requested = path
            if requested is None:
                request = getattr(websocket, "request", None)
                requested = getattr(request, "path", "/")
            expected = urlsplit(requested or "/").path
            if expected != self.config.transports.websocket.path:
                await send_json(
                    {
                        "type": "error",
                        "code": "not_found",
                        "message": f"connect to {self.config.transports.websocket.path}",
                    }
                )
                close_code, close_reason = 1008, "invalid path"
                return
            while True:
                try:
                    raw = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=self.config.server.idle_timeout_seconds,
                    )
                except TimeoutError:
                    await send_json(
                        {
                            "type": "error",
                            "code": "idle_timeout",
                            "message": "connection idle timeout",
                        }
                    )
                    close_code, close_reason = 1001, "idle timeout"
                    return
                if isinstance(raw, str):
                    framed = raw.encode("utf-8")
                    if not framed.endswith(b"\n"):
                        framed += b"\n"
                else:
                    framed = bytes(raw)
                for item in decoder.feed(framed):
                    if hasattr(item, "value"):
                        await connection.handle_control(item.value)
                    else:
                        await connection.handle_audio(item.data)
        except ConnectionRejected as exc:
            close_code, close_reason = 1008, str(exc)
        except ProtocolError as exc:
            with contextlib.suppress(Exception):
                await send_json({"type": "error", "code": "protocol_error", "message": str(exc)})
            close_code, close_reason = 1002, "protocol error"
        except Exception as exc:
            received = getattr(exc, "rcvd", None)
            received_code = getattr(received, "code", None)
            if received_code not in {1000, 1001, 1005, 1006}:
                with contextlib.suppress(Exception):
                    await send_json(
                        {
                            "type": "error",
                            "code": "internal_error",
                            "message": f"{exc.__class__.__name__}: {exc}",
                        }
                    )
            close_code = 1000 if received_code == 1000 else 1011
            close_reason = getattr(received, "reason", "") or "websocket closed"
        finally:
            try:
                await connection.close()
            finally:
                self._clients.discard(websocket)
                with contextlib.suppress(Exception):
                    await websocket.close(code=close_code, reason=close_reason[:120])

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            with contextlib.suppress(Exception):
                await server.wait_closed()
        clients = list(self._clients)
        for websocket in clients:
            with contextlib.suppress(Exception):
                await websocket.close(code=1001, reason="server shutdown")
        if clients:
            await asyncio.sleep(0)
        self._clients.clear()
        self._state = "stopped"

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.config.transports.websocket.enabled,
            "state": self._state,
            "host": self.config.server.host,
            "port": self.config.server.ws_port,
            "path": self.config.transports.websocket.path,
            "connections": len(self._clients),
            "error": self._error,
        }
