from __future__ import annotations

from collections.abc import AsyncIterator

from voicebridge.models import ProviderCapabilities, TranscriptEvent
from voicebridge.providers.base import ASRProvider, ProviderRequest


class MockProvider(ASRProvider):
    """Deterministic provider used for protocol tests and installation checks."""

    name = "mock"
    capabilities = ProviderCapabilities(
        partial_results=True,
        final_results=True,
        requires_network=False,
        notes="no credentials or network required",
    )

    async def stream(self, request: ProviderRequest) -> AsyncIterator[TranscriptEvent]:
        total = 0
        threshold = max(1, int(request.options.get("partial_after_bytes", 3_200)))
        partial_words = [
            str(item)
            for item in request.options.get(
                "partial_words", ["Mock", "Mock transcription"]
            )
            if str(item)
        ]
        word_index = 0
        async for chunk in request.audio:
            total += len(chunk)
            while word_index < len(partial_words) and total >= threshold * (word_index + 1):
                yield TranscriptEvent(
                    text=partial_words[word_index],
                    final=False,
                    confidence=1.0,
                    provider=self.name,
                )
                word_index += 1
        final_text = str(
            request.options.get("transcript", "Mock transcription.")
        )
        yield TranscriptEvent(
            text=final_text,
            final=True,
            confidence=1.0,
            provider=self.name,
            metadata={"bytes": total, "sessionId": request.session_id},
        )
