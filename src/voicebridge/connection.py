from __future__ import annotations

import json
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from voicebridge.models import AudioFormat, AudioFormatError
from voicebridge.service import SessionBusyError, SessionHandle, VoiceBridgeService

SendJson = Callable[[dict[str, Any]], Awaitable[None]]


class ConnectionRejected(RuntimeError):
    """Raised when a connection fails authentication or protocol validation."""


class ConnectionSession:
    """Protocol state machine shared by WebSocket, TCP, and serial transports."""

    def __init__(
        self,
        service: VoiceBridgeService,
        send_json: SendJson,
        *,
        preauthenticated: bool = False,
    ) -> None:
        self.service = service
        self.send_json = send_json
        self.authenticated = preauthenticated or not service.config.server.require_token
        self.hello_seen = False
        self.handle: SessionHandle | None = None
        self._closed = False

    def _check_token(self, supplied: str) -> bool:
        expected = self.service.config.server.token
        if not self.service.config.server.require_token:
            return True
        return bool(expected) and secrets.compare_digest(supplied, expected)

    async def handle_control(self, message: dict[str, Any]) -> None:
        kind = str(message.get("type") or "").strip().lower()
        if kind == "hello":
            supplied = str(message.get("token") or "")
            if not self._check_token(supplied):
                await self.send_json(
                    {"type": "error", "code": "unauthorized", "message": "invalid token"}
                )
                raise ConnectionRejected("invalid token")
            self.authenticated = True
            self.hello_seen = True
            await self.send_json(
                {
                    "type": "hello_ack",
                    "ok": True,
                    "service": "voice-input-bridge",
                    "protocol": 1,
                    "requiresToken": self.service.config.server.require_token,
                    "providers": [self.service.config.asr.provider],
                }
            )
            return

        if not self.authenticated:
            await self.send_json(
                {"type": "error", "code": "unauthorized", "message": "send hello first"}
            )
            raise ConnectionRejected("authentication required")

        if kind == "start":
            await self._start(message)
            return
        if kind == "stop":
            await self._stop()
            return
        if kind == "ping":
            await self.send_json({"type": "pong"})
            return
        if kind in {"status", "get_status"}:
            await self.send_json({"type": "status", **self.service.status_snapshot()})
            return
        await self.send_json(
            {
                "type": "error",
                "code": "unsupported_message",
                "message": f"unsupported control message: {kind or '<empty>'}",
            }
        )

    async def _start(self, message: dict[str, Any]) -> None:
        if self.handle is not None and self.handle.active:
            await self.send_json(
                {
                    "type": "error",
                    "code": "busy",
                    "message": "a session is already active on this connection",
                }
            )
            return
        try:
            audio_format = AudioFormat.from_message(message)
        except AudioFormatError as exc:
            await self.send_json(
                {"type": "error", "code": "invalid_audio_format", "message": str(exc)}
            )
            return
        session_id = str(message.get("sessionId") or message.get("session_id") or "").strip()
        language = str(message.get("language") or "").strip() or None
        try:
            self.handle = await self.service.begin_session(
                audio_format,
                session_id=session_id or None,
                language=language,
                emit=self.send_json,
            )
        except SessionBusyError as exc:
            await self.send_json(
                {"type": "error", "code": "busy", "message": str(exc)}
            )

    async def _stop(self) -> None:
        if self.handle is None:
            await self.send_json({"type": "stopped", "ok": True})
            return
        status = await self.service.stop(self.handle)
        await self.send_json(
            {
                "type": "stopped",
                "ok": status.state != "error",
                "session": status.to_dict(),
            }
        )
        self.handle = None

    async def handle_audio(self, data: bytes) -> None:
        if not self.authenticated:
            await self.send_json(
                {"type": "error", "code": "unauthorized", "message": "send hello first"}
            )
            return
        if self.handle is None or not self.handle.active:
            await self.send_json(
                {
                    "type": "error",
                    "code": "no_active_session",
                    "message": "send a start message before audio",
                }
            )
            return
        await self.handle.push(data)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.handle is not None:
            await self.service.stop(self.handle)
            self.handle = None


def parse_json_message(raw: str | bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON message: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("control messages must be JSON objects")
    return value
