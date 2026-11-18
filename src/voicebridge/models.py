from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AudioFormatError(ValueError):
    """Raised when a device declares an unsupported or inconsistent audio format."""


@dataclass(frozen=True, slots=True)
class AudioFormat:
    """PCM audio format carried by a device session."""

    sample_rate: int = 16_000
    channels: int = 1
    bits_per_sample: int = 16
    encoding: str = "pcm_s16le"

    def __post_init__(self) -> None:
        if self.sample_rate < 8_000 or self.sample_rate > 192_000:
            raise AudioFormatError("sample_rate must be between 8000 and 192000")
        if self.channels < 1 or self.channels > 8:
            raise AudioFormatError("channels must be between 1 and 8")
        if self.bits_per_sample not in {8, 16, 24, 32}:
            raise AudioFormatError("bits_per_sample must be one of 8, 16, 24, or 32")
        if not self.encoding.startswith("pcm"):
            raise AudioFormatError("only PCM encodings are supported")

    @property
    def bytes_per_sample(self) -> int:
        return self.bits_per_sample // 8

    @property
    def frame_size(self) -> int:
        return self.channels * self.bytes_per_sample

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.frame_size

    def duration_seconds(self, byte_count: int) -> float:
        return byte_count / self.bytes_per_second if self.bytes_per_second else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "sampleRate": self.sample_rate,
            "channels": self.channels,
            "bitsPerSample": self.bits_per_sample,
            "encoding": self.encoding,
        }

    @classmethod
    def from_message(cls, message: Mapping[str, Any]) -> AudioFormat:
        sample_rate = message.get("sampleRate", message.get("sample_rate", 16_000))
        channels = message.get("channels", 1)
        bits = message.get("bitsPerSample", message.get("bits_per_sample", 16))
        encoding = str(message.get("encoding", f"pcm_s{bits}le"))
        try:
            return cls(
                sample_rate=int(sample_rate),
                channels=int(channels),
                bits_per_sample=int(bits),
                encoding=encoding,
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, AudioFormatError):
                raise
            raise AudioFormatError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    partial_results: bool = True
    final_results: bool = True
    requires_network: bool = False
    native_sample_rate: int | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "partialResults": self.partial_results,
            "finalResults": self.final_results,
            "requiresNetwork": self.requires_network,
            "nativeSampleRate": self.native_sample_rate,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class InputCapabilities:
    partial_text: bool = True
    backspace: bool = True
    foreground_guard: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "partialText": self.partial_text,
            "backspace": self.backspace,
            "foregroundGuard": self.foreground_guard,
            "note": self.note,
        }


@dataclass(slots=True)
class TranscriptEvent:
    text: str
    final: bool = False
    confidence: float | None = None
    provider: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": "final" if self.final else "partial",
            "text": self.text,
            "provider": self.provider,
        }
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


class SessionState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    LISTENING = "listening"
    FINISHING = "finishing"
    COMPLETED = "completed"
    ERROR = "error"
    BUSY = "busy"

    def __str__(self) -> str:
        return self.value


@dataclass(slots=True)
class SessionStatus:
    session_id: str
    state: SessionState = SessionState.IDLE
    provider: str = ""
    audio: AudioFormat = field(default_factory=AudioFormat)
    frames: int = 0
    bytes_received: int = 0
    dropped_bytes: int = 0
    finals: int = 0
    last_partial: str = ""
    last_final: str = ""
    first_partial_ms: float | None = None
    error: str | None = None
    started_at: float | None = None
    stopped_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "state": str(self.state),
            "provider": self.provider,
            "audio": self.audio.to_dict(),
            "frames": self.frames,
            "bytesReceived": self.bytes_received,
            "droppedBytes": self.dropped_bytes,
            "durationSeconds": round(self.audio.duration_seconds(self.bytes_received), 3),
            "finals": self.finals,
            "lastPartial": self.last_partial,
            "lastFinal": self.last_final,
            "firstPartialMs": self.first_partial_ms,
            "error": self.error,
            "startedAt": self.started_at,
            "stoppedAt": self.stopped_at,
        }
