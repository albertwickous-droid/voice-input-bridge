from __future__ import annotations

import asyncio
import contextlib
import os
import queue
import threading
from collections.abc import AsyncIterator
from typing import Any

from voicebridge.models import ProviderCapabilities, TranscriptEvent
from voicebridge.providers.base import (
    ASRProvider,
    ProviderError,
    ProviderRequest,
    ProviderUnavailable,
)

DEFAULT_MODEL = "paraformer-realtime-v2"


def _safe_error(exc: BaseException) -> str:
    text = str(exc).strip()
    return text[:1000] if text else exc.__class__.__name__


class AliyunParaformerProvider(ASRProvider):
    """Alibaba Cloud Paraformer Realtime V2 through the DashScope Python SDK."""

    name = "aliyun"
    capabilities = ProviderCapabilities(
        partial_results=True,
        final_results=True,
        requires_network=True,
        native_sample_rate=16_000,
        notes="DashScope Paraformer Realtime V2; PCM 8/16 kHz, mono, 16-bit",
    )

    @staticmethod
    def _parse_event(event: dict[str, Any]) -> TranscriptEvent | None:
        payload = event.get("payload") or {}
        sentence = (payload.get("output") or {}).get("sentence") or {}
        if not sentence or sentence.get("heartbeat"):
            return None
        text = str(sentence.get("text") or "")
        if not text:
            return None
        final = bool(sentence.get("sentence_end")) or sentence.get("end_time") is not None
        return TranscriptEvent(
            text=text,
            final=final,
            provider="aliyun",
            metadata={
                key: value
                for key, value in sentence.items()
                if key in {"begin_time", "end_time", "sentence_end"}
            },
        )

    async def stream(self, request: ProviderRequest) -> AsyncIterator[TranscriptEvent]:
        fmt = request.audio_format
        if fmt.channels != 1 or fmt.bits_per_sample != 16 or fmt.sample_rate not in {8_000, 16_000}:
            raise ProviderError("Aliyun Paraformer requires mono 16-bit PCM at 8000 or 16000 Hz")
        try:
            from dashscope import Client
        except ImportError as exc:
            raise ProviderUnavailable(
                "install the Aliyun extra: pip install 'voice-input-bridge[aliyun]'"
            ) from exc

        api_key = str(
            request.options.get("api_key") or os.environ.get("DASHSCOPE_API_KEY", "")
        ).strip()
        if not api_key:
            raise ProviderUnavailable("Aliyun requires DASHSCOPE_API_KEY")
        workspace = (
            str(
                request.options.get("workspace_id")
                or request.options.get("workspace")
                or os.environ.get("DASHSCOPE_WORKSPACE_ID", "")
            ).strip()
            or None
        )
        region = (
            str(request.options.get("region") or os.environ.get("DASHSCOPE_REGION", "")).strip()
            or None
        )
        vocabulary_id = (
            str(
                request.options.get("vocabulary_id")
                or os.environ.get("DASHSCOPE_VOCABULARY_ID", "")
            ).strip()
            or None
        )
        phrase_id = str(request.options.get("phrase_id") or "").strip() or None
        model = str(request.options.get("model", DEFAULT_MODEL))
        language_hints = request.options.get("language_hints") or ["zh", "en"]
        parameters = dict(request.options.get("parameters") or {})
        parameters.setdefault("language_hints", list(language_hints))
        final_timeout = float(request.options.get("final_timeout_seconds", 20))

        audio_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=200)
        event_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=1000)
        loop = asyncio.get_running_loop()
        receiver_done = threading.Event()
        receiver_errors: list[BaseException] = []

        def publish(kind: str, payload: Any = None) -> None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(event_queue.put_nowait, (kind, payload))

        def receive_events(session: Any) -> None:
            try:
                for raw_event in session.events():
                    if not isinstance(raw_event, dict):
                        continue
                    parsed = self._parse_event(raw_event)
                    if parsed is not None:
                        publish("event", parsed)
            except BaseException as exc:
                receiver_errors.append(exc)
            finally:
                # Ensure all previously scheduled event callbacks run before the
                # worker publishes its terminal "done" marker.
                barrier_done = threading.Event()

                def barrier() -> None:
                    with contextlib.suppress(asyncio.QueueFull):
                        event_queue.put_nowait(("receiver_end", None))
                    barrier_done.set()

                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(barrier)
                    barrier_done.wait(5)
                receiver_done.set()

        def run_session() -> None:
            client = None
            session = None
            try:
                kwargs: dict[str, Any] = {"api_key": api_key}
                if workspace:
                    kwargs["workspace"] = workspace
                if region:
                    kwargs["region"] = region
                client = Client(**kwargs)
                recognize_kwargs: dict[str, Any] = {
                    "model": model,
                    "format": "pcm",
                    "sample_rate": fmt.sample_rate,
                    "vocabulary_id": vocabulary_id,
                    "phrase_id": phrase_id,
                    "parameters": parameters,
                }
                if request.options.get("disfluency_removal_enabled") is not None:
                    recognize_kwargs["disfluency_removal_enabled"] = bool(
                        request.options["disfluency_removal_enabled"]
                    )
                if request.options.get("diarization_enabled") is not None:
                    recognize_kwargs["diarization_enabled"] = bool(
                        request.options["diarization_enabled"]
                    )
                session = client.audio.asr.recognize(**recognize_kwargs)
                session.start()
                publish("connected")
                receiver = threading.Thread(
                    target=receive_events,
                    args=(session,),
                    name="voicebridge-aliyun-events",
                    daemon=True,
                )
                receiver.start()
                while True:
                    chunk = audio_queue.get()
                    if chunk is None:
                        break
                    session.send_audio_frame(chunk)
                session.stop()
                if not receiver_done.wait(final_timeout):
                    raise TimeoutError(
                        f"no final Aliyun result within {final_timeout:g}s after audio ended"
                    )
                if receiver_errors:
                    raise receiver_errors[0]
            except BaseException as exc:
                publish("error", str(_safe_error(exc)))
            finally:
                if session is not None:
                    with contextlib.suppress(Exception):
                        session.close()
                if client is not None:
                    with contextlib.suppress(Exception):
                        client.close()
                receiver_done.set()
                publish("done")

        async def pump_audio() -> None:
            try:
                async for chunk in request.audio:
                    if chunk:
                        await asyncio.to_thread(audio_queue.put, chunk, True, 5)
            finally:
                with contextlib.suppress(queue.Full):
                    audio_queue.put_nowait(None)

        def pump_finished(task: asyncio.Task[None]) -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                publish("error", f"audio pump failed: {_safe_error(exc)}")

        def wake_worker() -> None:
            # The worker may be blocked on the bounded audio queue.  Drain it so
            # it can observe the terminal marker without waiting for the device.
            while True:
                try:
                    audio_queue.get_nowait()
                except queue.Empty:
                    break
            with contextlib.suppress(queue.Full):
                audio_queue.put_nowait(None)

        worker = threading.Thread(
            target=run_session,
            name="voicebridge-aliyun-session",
            daemon=True,
        )
        pump = asyncio.create_task(pump_audio())
        pump.add_done_callback(pump_finished)
        worker.start()
        failure: str | None = None
        try:
            while True:
                kind, payload = await event_queue.get()
                if kind == "event":
                    yield payload
                elif kind == "error":
                    failure = str(payload)
                    break
                elif kind == "done":
                    break
                elif kind == "receiver_end":
                    continue
        finally:
            # Do not await the audio pump here.  It may still be waiting on the
            # input stream when the provider reports an error or finishes early.
            if not pump.done():
                pump.cancel()
            wake_worker()
            pump_result = (await asyncio.gather(pump, return_exceptions=True))[0]
            if (
                failure is None
                and isinstance(pump_result, BaseException)
                and not isinstance(pump_result, asyncio.CancelledError)
            ):
                failure = f"audio pump failed: {_safe_error(pump_result)}"
        if failure:
            raise ProviderError(f"Alibaba Cloud Paraformer failed: {failure}")
