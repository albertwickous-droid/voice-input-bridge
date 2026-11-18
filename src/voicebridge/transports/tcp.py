from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from voicebridge.config import BridgeConfig
from voicebridge.connection import ConnectionRejected, ConnectionSession
from voicebridge.protocol import ProtocolError, StreamDecoder
from voicebridge.service import VoiceBridgeService


class TcpTransport:
    name = "tcp"

    def __init__(self, config: BridgeConfig, service: VoiceBridgeService) -> None:
        self.config = config
        self.service = service
        self._server: asyncio.AbstractServer | None = None
        self._connections = 0
        self._state = "stopped"
        self._error: str | None = None

    async def start(self) -> bool:
        if not self.config.transports.tcp.enabled:
            self._state = "disabled"
            return True
        try:
            self._server = await asyncio.start_server(
                self._handle_client,
                self.config.server.host,
                self.config.server.tcp_port,
                limit=1024 * 1024,
            )
        except Exception as exc:
            self._state = "error"
            self._error = f"{exc.__class__.__name__}: {exc}"
            return False
        self._state = "listening"
        self._error = None
        return True

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._connections += 1
        writer.get_extra_info("peername")
        write_lock = asyncio.Lock()

        async def send_json(message: dict[str, Any]) -> None:
            data = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
            async with write_lock:
                writer.write(data)
                await writer.drain()

        connection = ConnectionSession(self.service, send_json)
        decoder = StreamDecoder(strict=True)
        try:
            while True:
                raw = await asyncio.wait_for(
                    reader.read(4096), timeout=self.config.server.idle_timeout_seconds
                )
                if not raw:
                    break
                for item in decoder.feed(raw):
                    if hasattr(item, "value"):
                        await connection.handle_control(item.value)
                    else:
                        await connection.handle_audio(item.data)
        except TimeoutError:
            with contextlib.suppress(Exception):
                await send_json(
                    {
                        "type": "error",
                        "code": "idle_timeout",
                        "message": "connection idle timeout",
                    }
                )
        except ConnectionRejected:
            pass
        except ProtocolError as exc:
            with contextlib.suppress(Exception):
                await send_json({"type": "error", "code": "protocol_error", "message": str(exc)})
        except (ConnectionError, asyncio.CancelledError):
            pass
        except Exception as exc:
            with contextlib.suppress(Exception):
                await send_json(
                    {
                        "type": "error",
                        "code": "internal_error",
                        "message": f"{exc.__class__.__name__}: {exc}",
                    }
                )
        finally:
            with contextlib.suppress(Exception):
                await connection.close()
            self._connections = max(0, self._connections - 1)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            with contextlib.suppress(Exception):
                await server.wait_closed()
        self._state = "stopped"

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.config.transports.tcp.enabled,
            "state": self._state,
            "host": self.config.server.host,
            "port": self.config.server.tcp_port,
            "connections": self._connections,
            "error": self._error,
        }
