from __future__ import annotations

import asyncio
import locale
import os
import shlex
import subprocess
import tempfile
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from voicebridge.models import ProviderCapabilities, TranscriptEvent
from voicebridge.providers.base import ASRProvider, ProviderError, ProviderRequest


class CommandProvider(ASRProvider):
    """Final-only adapter for local or third-party command-line ASR tools."""

    name = "command"
    capabilities = ProviderCapabilities(
        partial_results=False,
        final_results=True,
        requires_network=False,
        notes="collects the utterance, writes a WAV, then runs a configured command",
    )

    @staticmethod
    def _decode_output(data: bytes | None, requested_encoding: str = "") -> str:
        if not data:
            return ""
        candidates = [requested_encoding] if requested_encoding else ["utf-8", locale.getpreferredencoding(False)]
        for encoding in candidates:
            if not encoding:
                continue
            try:
                return data.decode(encoding).lstrip("\ufeff")
            except (LookupError, UnicodeDecodeError):
                continue
        return data.decode("utf-8", errors="replace").lstrip("\ufeff")

    async def stream(self, request: ProviderRequest) -> AsyncIterator[TranscriptEvent]:
        command_value = request.options.get("command")
        if isinstance(command_value, str):
            command = shlex.split(command_value)
        elif isinstance(command_value, list):
            command = [str(item) for item in command_value]
        else:
            raise ProviderError("command provider requires command = [...]")
        if not command:
            raise ProviderError("command provider command cannot be empty")

        max_bytes = int(
            float(request.options.get("max_audio_seconds", 120)) * request.audio_format.bytes_per_second
        )
        audio = bytearray()
        async for chunk in request.audio:
            if not chunk:
                continue
            remaining = max_bytes - len(audio)
            if remaining <= 0:
                break
            audio.extend(chunk[:remaining])
        if not audio:
            raise ProviderError("no audio received")

        timeout = float(request.options.get("timeout_seconds", 180))
        language_short = request.language.split("-", 1)[0]
        with tempfile.TemporaryDirectory(prefix="voicebridge-command-") as directory:
            wav_path = Path(directory) / "utterance.wav"
            with wave.open(str(wav_path), "wb") as stream:
                stream.setnchannels(request.audio_format.channels)
                stream.setsampwidth(request.audio_format.bytes_per_sample)
                stream.setframerate(request.audio_format.sample_rate)
                stream.writeframes(bytes(audio))
            format_values: dict[str, Any] = {
                "wav": str(wav_path),
                "language": request.language,
                "language_short": language_short,
                "sample_rate": request.audio_format.sample_rate,
            }
            expanded = [argument.format_map(format_values) for argument in command]
            environment = {
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            }
            try:
                completed = await asyncio.to_thread(
                    subprocess.run,
                    expanded,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                    env=environment,
                )
            except FileNotFoundError as exc:
                raise ProviderError(f"command executable not found: {expanded[0]}") from exc
            except subprocess.TimeoutExpired as exc:
                raise ProviderError(f"command timed out after {timeout:g}s") from exc
            output_encoding = str(request.options.get("output_encoding", "")).strip()
            stdout = self._decode_output(completed.stdout, output_encoding)
            stderr = self._decode_output(completed.stderr, output_encoding)
            if completed.returncode != 0:
                detail = (stderr or stdout or "").strip()[-500:]
                raise ProviderError(
                    f"command exited with {completed.returncode}: {detail or 'no output'}"
                )
            text = stdout.strip()
            if text:
                yield TranscriptEvent(
                    text=text,
                    final=True,
                    provider=self.name,
                    metadata={"bytes": len(audio), "command": expanded[0]},
                )
