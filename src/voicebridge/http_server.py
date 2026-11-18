from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from voicebridge.config import BridgeConfig

JsonProvider = Callable[[], dict[str, Any]]


class HttpStatusServer:
    """Read-only HTTP status API with no third-party HTTP dependency."""

    def __init__(
        self,
        config: BridgeConfig,
        *,
        health_provider: JsonProvider,
        status_provider: JsonProvider,
        protocol_provider: JsonProvider,
    ) -> None:
        self.config = config
        self.health_provider = health_provider
        self.status_provider = status_provider
        self.protocol_provider = protocol_provider
        self._server: asyncio.AbstractServer | None = None
        self._connections = 0
        self._state = "stopped"
        self._error: str | None = None

    async def start(self) -> bool:
        try:
            self._server = await asyncio.start_server(
                self._handle_client,
                self.config.server.http_host,
                self.config.server.http_port,
                limit=16 * 1024,
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
        keep_body = True
        try:
            request = await asyncio.wait_for(self._read_request(reader), timeout=5)
            method, target = request
            path = urlsplit(target).path
            if method not in {"GET", "HEAD"}:
                status, body = 405, {"error": "method_not_allowed"}
            elif path == "/health":
                status, body = 200, self.health_provider()
            elif path == "/v1/status":
                status, body = 200, self.status_provider()
            elif path == "/v1/protocol":
                status, body = 200, self.protocol_provider()
            elif path == "/":
                status, body = 200, {
                    "service": "voice-input-bridge",
                    "endpoints": ["/health", "/v1/status", "/v1/protocol"],
                }
            else:
                status, body = 404, {"error": "not_found"}
            keep_body = method != "HEAD"
        except (TimeoutError, ValueError, asyncio.LimitOverrunError) as exc:
            status, body = 400, {"error": "bad_request", "detail": str(exc)}
        except Exception as exc:
            status, body = 500, {
                "error": "internal_error",
                "detail": f"{exc.__class__.__name__}: {exc}",
            }
        try:
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            reason = {
                200: "OK",
                400: "Bad Request",
                404: "Not Found",
                405: "Method Not Allowed",
                500: "Internal Server Error",
            }.get(status, "Error")
            headers = [
                f"HTTP/1.1 {status} {reason}",
                "Content-Type: application/json; charset=utf-8",
                f"Content-Length: {len(encoded)}",
                "Cache-Control: no-store",
                "Access-Control-Allow-Origin: *",
                "X-Content-Type-Options: nosniff",
                "Connection: close",
                "",
                "",
            ]
            writer.write("\r\n".join(headers).encode("ascii"))
            if keep_body:
                writer.write(encoded)
            await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._connections = max(0, self._connections - 1)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    @staticmethod
    async def _read_request(reader: asyncio.StreamReader) -> tuple[str, str]:
        request_line = await reader.readline()
        if not request_line:
            raise ValueError("empty request")
        if len(request_line) > 8192:
            raise ValueError("request line too long")
        try:
            method, target, version = request_line.decode("ascii").strip().split(" ", 2)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("invalid request line") from exc
        if not version.startswith("HTTP/"):
            raise ValueError("invalid HTTP version")
        total = len(request_line)
        while True:
            line = await reader.readline()
            if not line:
                break
            total += len(line)
            if total > 16 * 1024:
                raise ValueError("request headers too large")
            if line in {b"\r\n", b"\n"}:
                break
        return method, target

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            with contextlib.suppress(Exception):
                await server.wait_closed()
        self._state = "stopped"

    def status(self) -> dict[str, Any]:
        return {
            "name": "http",
            "state": self._state,
            "host": self.config.server.http_host,
            "port": self.config.server.http_port,
            "connections": self._connections,
            "error": self._error,
        }
