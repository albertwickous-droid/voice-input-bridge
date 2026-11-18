from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

from voicebridge.models import ProviderCapabilities, TranscriptEvent
from voicebridge.providers.base import (
    ASRProvider,
    ProviderError,
    ProviderRequest,
    ProviderUnavailable,
)


class DeepgramProvider(ASRProvider):
    """Deepgram realtime WebSocket adapter using only the websockets dependency."""

    name = "deepgram"
    capabilities = ProviderCapabilities(
        partial_results=True,
        final_results=True,
        requires_network=True,
        native_sample_rate=16_000,
        notes="Deepgram Listen API; linear16 PCM over WebSocket",
    )

    @staticmethod
    def _parse_result(message: dict[str, Any]) -> TranscriptEvent | None:
        if message.get("type") != "Results":
            return None
        alternatives = (message.get("channel") or {}).get("alternatives") or []
        if not alternatives:
            return None
        alternative = alternatives[0]
        text = str(alternative.get("transcript") or "").strip()
        if not text:
            return None
        confidence = alternative.get("confidence")
        final = bool(message.get("is_final")) or bool(message.get("speech_final"))
        return TranscriptEvent(
            text=text,
            final=final,
            confidence=float(confidence) if confidence is not None else None,
            provider="deepgram",
            metadata={
                "duration": message.get("duration"),
                "start": message.get("start"),
                "speechFinal": bool(message.get("speech_final")),
            },
        )

    async def stream(self, request: ProviderRequest) -> AsyncIterator[TranscriptEvent]:
        try:
            from websockets.asyncio.client import connect
            from websockets.exceptions import ConnectionClosed
        except ImportError as exc:
            raise ProviderUnavailable("install websockets>=13.1") from exc

        fmt = request.audio_format
        if fmt.bits_per_sample != 16:
            raise ProviderError("Deepgram linear16 requires 16-bit PCM")
        api_key = str(
            request.options.get("api_key") or os.environ.get("DEEPGRAM_API_KEY", "")
        ).strip()
        if not api_key:
            raise ProviderUnavailable("Deepgram requires DEEPGRAM_API_KEY")
        endpoint = str(
            request.options.get("endpoint", "wss://api.deepgram.com/v1/listen")
        )
        params = {
            "encoding": "linear16",
            "sample_rate": fmt.sample_rate,
            "channels": fmt.channels,
            "model": request.options.get("model", "nova-3"),
            "language": request.options.get("language", request.language),
            "smart_format": str(
                bool(request.options.get("smart_format", True))
            ).lower(),
            "punctuate": str(bool(request.options.get("punctuate", True))).lower(),
            "interim_results": str(
                bool(request.options.get("interim_results", True))
            ).lower(),
        }
        separator = "&" if "?" in endpoint else "?"
        uri = endpoint + separator + urlencode(params)
        headers = {"Authorization": f"Token {api_key}"}
        final_timeout = float(request.options.get("final_timeout_seconds", 20))

        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=1000)
        last_final_key: tuple[Any, Any, str] | None = None

        async def receive_events(websocket: Any) -> None:
            try:
                async for raw in websocket:
                    try:
                        message = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if not isinstance(message, dict):
                        continue
                    kind = message.get("type")
                    if kind == "Error":
                        await queue.put(("error", str(message.get("description") or message)))
                        continue
                    event = self._parse_result(message)
                    if event is None:
                        continue
                    if event.final:
                        nonlocal last_final_key
                        key = (
                            event.metadata.get("start"),
                            event.metadata.get("duration"),
                            event.text,
                        )
                        if key == last_final_key:
                            continue
                        last_final_key = key
                    await queue.put(("event", event))
            except ConnectionClosed:
                pass
            except BaseException as exc:
                await queue.put(("error", str(exc)))
            finally:
                await queue.put(("done", None))

        async with connect(
            uri,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=20,
            max_size=8 * 1024 * 1024,
        ) as websocket:
            receiver = asyncio.create_task(receive_events(websocket))

            async def pump_audio() -> None:
                async for chunk in request.audio:
                    if chunk:
                        await websocket.send(chunk)
                await websocket.send(json.dumps({"type": "CloseStream"}))

            def pump_finished(task: asyncio.Task[None]) -> None:
                if task.cancelled():
                    return
                exc = task.exception()
                if exc is not None:
                    with contextlib.suppress(asyncio.QueueFull):
                        queue.put_nowait(("error", f"audio pump failed: {exc}"))

            pump = asyncio.create_task(pump_audio())
            pump.add_done_callback(pump_finished)
            failure: str | None = None
            try:
                while True:
                    timeout = final_timeout if pump.done() else None
                    try:
                        kind, payload = await asyncio.wait_for(queue.get(), timeout=timeout)
                    except TimeoutError as exc:
                        raise ProviderError(
                            f"no final Deepgram result within {final_timeout:g}s"
                        ) from exc
                    if kind == "event":
                        yield payload
                    elif kind == "error":
                        failure = str(payload)
                        break
                    elif kind == "done":
                        break
            finally:
                # A remote error can arrive while the device is still sending.
                # Cancel the sender instead of waiting for request.audio to end.
                if not pump.done():
                    pump.cancel()
                if not receiver.done():
                    receiver.cancel()
                results = await asyncio.gather(pump, receiver, return_exceptions=True)
                pump_result = results[0]
                if (
                    failure is None
                    and isinstance(pump_result, BaseException)
                    and not isinstance(pump_result, asyncio.CancelledError)
                ):
                    failure = f"audio pump failed: {pump_result}"
            if failure:
                raise ProviderError(f"Deepgram failed: {failure}")
