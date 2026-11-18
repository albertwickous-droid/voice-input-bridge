from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from voicebridge.config import BridgeConfig
from voicebridge.input.base import InputError, StreamingTextCommitter
from voicebridge.input.factory import create_text_sink
from voicebridge.models import AudioFormat, SessionState, SessionStatus, TranscriptEvent
from voicebridge.providers.base import ProviderError, ProviderRequest, ProviderUnavailable
from voicebridge.providers.registry import create_provider

EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]


class SessionBusyError(RuntimeError):
    """Raised when a second simultaneous ASR session is requested."""


class SessionHandle:
    def __init__(
        self,
        service: VoiceBridgeService,
        session_id: str,
        audio_format: AudioFormat,
        language: str,
        emit: EventEmitter,
    ) -> None:
        self.service = service
        self.emit = emit
        self.status = SessionStatus(
            session_id=session_id,
            state=SessionState.STARTING,
            provider=service.config.asr.provider,
            audio=audio_format,
            started_at=time.time(),
        )
        self.language = language
        self.audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=64)
        self.task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._max_bytes = int(
            service.config.server.max_audio_seconds * audio_format.bytes_per_second
        )

    @property
    def active(self) -> bool:
        return self.status.state in {
            SessionState.STARTING,
            SessionState.LISTENING,
            SessionState.FINISHING,
        }

    async def push(self, data: bytes) -> bool:
        if not data or not self.active or self._stop_requested:
            return False
        remaining = self._max_bytes - self.status.bytes_received
        if remaining <= 0:
            self.status.dropped_bytes += len(data)
            return False
        if len(data) > remaining:
            self.status.dropped_bytes += len(data) - remaining
            data = data[:remaining]
        try:
            self.audio_queue.put_nowait(data)
        except asyncio.QueueFull:
            dropped = self.audio_queue.get_nowait()
            self.status.dropped_bytes += len(dropped or b"")
            self.audio_queue.put_nowait(data)
        self.status.frames += 1
        self.status.bytes_received += len(data)
        return True

    async def stop(self) -> None:
        if self._stop_requested:
            return
        self._stop_requested = True
        self.status.state = SessionState.FINISHING
        try:
            self.audio_queue.put_nowait(None)
        except asyncio.QueueFull:
            # A stopped session must never wait for a full bounded queue.  Drop
            # queued audio and deliver the end marker immediately.
            while True:
                try:
                    dropped = self.audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if dropped is not None:
                    self.status.dropped_bytes += len(dropped)
            self.audio_queue.put_nowait(None)

    async def wait(self) -> SessionStatus:
        if self.task is not None:
            await self.task
        return self.status

    def to_dict(self) -> dict[str, Any]:
        return self.status.to_dict()


class VoiceBridgeService:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self._lock = asyncio.Lock()
        self._active: SessionHandle | None = None
        self._last_status: SessionStatus | None = None

    async def begin_session(
        self,
        audio_format: AudioFormat,
        *,
        session_id: str | None = None,
        language: str | None = None,
        emit: EventEmitter,
    ) -> SessionHandle:
        async with self._lock:
            if self._active is not None and self._active.active:
                raise SessionBusyError(
                    f"session {self._active.status.session_id} is already active"
                )
            handle = SessionHandle(
                self,
                session_id=session_id or uuid4().hex,
                audio_format=audio_format,
                language=language or self.config.asr.language,
                emit=emit,
            )
            self._active = handle
            handle.task = asyncio.create_task(
                self._run_session(handle),
                name=f"voicebridge-session-{handle.status.session_id}",
            )
            return handle

    async def _run_session(self, handle: SessionHandle) -> None:
        status = handle.status
        provider = None
        committer: StreamingTextCommitter | None = None
        watchdog: asyncio.Task[None] | None = None
        try:
            sink = create_text_sink(self.config.input)
            committer = StreamingTextCommitter(
                sink,
                send_partial=self.config.input.send_partial,
                final_suffix=self.config.input.final_suffix,
            )
            if not committer.start():
                raise InputError("text input backend could not start")
            provider = create_provider(self.config.asr.provider)
            status.state = SessionState.LISTENING
            await handle.emit(
                {
                    "type": "listening",
                    "sessionId": status.session_id,
                    "provider": provider.name,
                    "audio": status.audio.to_dict(),
                }
            )

            async def audio_source():
                while True:
                    chunk = await handle.audio_queue.get()
                    if chunk is None:
                        return
                    yield chunk

            async def stop_after_limit() -> None:
                seconds = self.config.server.max_audio_seconds
                await asyncio.sleep(seconds)
                if handle.active and not handle._stop_requested:
                    await handle.emit(
                        {
                            "type": "warning",
                            "code": "max_audio_seconds",
                            "message": f"session reached the {seconds:g}s limit",
                            "sessionId": status.session_id,
                        }
                    )
                    await handle.stop()

            watchdog = asyncio.create_task(stop_after_limit(), name="voicebridge-watchdog")
            request = ProviderRequest(
                session_id=status.session_id,
                audio=audio_source(),
                audio_format=status.audio,
                language=handle.language,
                options=self.config.asr.options,
            )
            listening_started_at = time.monotonic()
            emitted_final = False
            async for event in provider.stream(request):
                if not event.final and status.first_partial_ms is None:
                    status.first_partial_ms = round(
                        (time.monotonic() - listening_started_at) * 1000, 1
                    )
                await self._apply_event(handle, committer, event)
                emitted_final = emitted_final or event.final
            if provider.capabilities.final_results and not emitted_final:
                await handle.emit(
                    {
                        "type": "warning",
                        "code": "provider_no_final",
                        "message": "ASR stream ended without a final transcript",
                        "sessionId": status.session_id,
                    }
                )
            status.state = SessionState.COMPLETED
        except SessionBusyError as exc:
            status.state = SessionState.BUSY
            status.error = str(exc)
            await handle.emit(
                {"type": "error", "code": "busy", "message": str(exc), "sessionId": status.session_id}
            )
        except (ProviderUnavailable, ProviderError, InputError) as exc:
            status.state = SessionState.ERROR
            status.error = str(exc)
            await handle.emit(
                {
                    "type": "error",
                    "code": "session_failed",
                    "message": str(exc),
                    "sessionId": status.session_id,
                }
            )
        except asyncio.CancelledError:
            status.state = SessionState.ERROR
            status.error = "session cancelled"
            raise
        except Exception as exc:
            status.state = SessionState.ERROR
            status.error = f"{exc.__class__.__name__}: {exc}"
            await handle.emit(
                {
                    "type": "error",
                    "code": "internal_error",
                    "message": status.error,
                    "sessionId": status.session_id,
                }
            )
        finally:
            if watchdog is not None:
                watchdog.cancel()
                await asyncio.gather(watchdog, return_exceptions=True)
            if committer is not None:
                committer.close()
                status.last_partial = ""
            if provider is not None:
                await provider.close()
            status.stopped_at = time.time()
            if status.state not in {SessionState.ERROR, SessionState.BUSY}:
                status.state = SessionState.COMPLETED
            self._last_status = status
            async with self._lock:
                if self._active is handle:
                    self._active = None
            await handle.emit({"type": "session_end", "session": status.to_dict()})

    async def _apply_event(
        self,
        handle: SessionHandle,
        committer: StreamingTextCommitter,
        event: TranscriptEvent,
    ) -> None:
        status = handle.status
        if event.final:
            ok = committer.final(event.text)
            if ok:
                status.last_final = event.text
                status.last_partial = ""
                status.finals += 1
            await handle.emit(event.to_dict())
        else:
            ok = committer.partial(event.text)
            if ok:
                status.last_partial = event.text
            await handle.emit(event.to_dict())
        if not ok:
            await handle.emit(
                {
                    "type": "warning",
                    "code": "text_input_paused",
                    "message": committer.sink.status().get("error")
                    or "text input could not apply the update",
                    "sessionId": status.session_id,
                }
            )

    async def stop(self, handle: SessionHandle) -> SessionStatus:
        await handle.stop()
        return await handle.wait()

    async def close(self) -> None:
        async with self._lock:
            handle = self._active
        if handle is not None:
            await handle.stop()
            await handle.wait()

    def status_snapshot(self) -> dict[str, Any]:
        active = self._active.to_dict() if self._active is not None else None
        return {
            "ok": True,
            "activeSession": active,
            "lastSession": self._last_status.to_dict() if self._last_status else None,
            "provider": self.config.asr.provider,
            "language": self.config.asr.language,
            "inputBackend": self.config.input.backend,
            "warnings": self.config.validate(),
        }
