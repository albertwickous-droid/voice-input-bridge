from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from voicebridge.models import AudioFormat, ProviderCapabilities, TranscriptEvent


class ProviderError(RuntimeError):
    """Raised when an ASR provider fails during a session."""


class ProviderUnavailable(ProviderError):
    """Raised when credentials, optional dependencies, or provider support are missing."""


@dataclass(slots=True)
class ProviderRequest:
    session_id: str
    audio: AsyncIterator[bytes]
    audio_format: AudioFormat
    language: str = "zh-CN"
    options: Mapping[str, Any] = field(default_factory=dict)


class ASRProvider(ABC):
    name = "base"
    capabilities = ProviderCapabilities(requires_network=False)

    @abstractmethod
    async def stream(self, request: ProviderRequest) -> AsyncIterator[TranscriptEvent]:
        raise NotImplementedError
        yield  # pragma: no cover

    async def close(self) -> None:
        return None
