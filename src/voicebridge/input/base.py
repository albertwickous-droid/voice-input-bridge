from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from voicebridge.models import InputCapabilities


class InputError(RuntimeError):
    """Raised when text cannot be injected into the foreground application."""


class InputUnavailable(InputError):
    """Raised when the requested platform input backend is unavailable."""


class TextSink(ABC):
    capabilities = InputCapabilities()

    def __init__(self, *, require_same_window: bool = True) -> None:
        self.require_same_window = require_same_window
        self._active = False
        self._phase = "idle"
        self._error: str | None = None
        self._inserted_updates = 0
        self._deleted_updates = 0

    @abstractmethod
    def start(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def insert_text(self, text: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def backspace(self, count: int) -> bool:
        raise NotImplementedError

    def finish(self) -> None:
        self._active = False
        self._phase = "idle"

    def close(self) -> None:
        self.finish()

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.__class__.__name__,
            "capabilities": self.capabilities.to_dict(),
            "active": self._active,
            "phase": self._phase,
            "insertedUpdates": self._inserted_updates,
            "deletedUpdates": self._deleted_updates,
            "error": self._error,
        }

    def _mark_paused(self, reason: str) -> None:
        self._phase = "paused"
        self._error = reason


def _common_prefix_length(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


class StreamingTextCommitter:
    """Turns cumulative ASR results into minimal text edits.

    ASR providers generally emit cumulative partial text for the current
    utterance and then a final version. This class deletes only the stale suffix
    of the previous partial and inserts only the new suffix.
    """

    def __init__(
        self,
        sink: TextSink,
        *,
        send_partial: bool = True,
        final_suffix: str = "",
    ) -> None:
        self.sink = sink
        self.send_partial = send_partial
        self.final_suffix = final_suffix
        self._current = ""
        self._started = False
        self._finished = False
        self.partial_updates = 0
        self.final_updates = 0

    def start(self) -> bool:
        if self._started:
            return True
        if not self.sink.start():
            return False
        self._started = True
        return True

    def partial(self, text: str) -> bool:
        if self._finished or not self._started or not self.send_partial:
            return False
        if not self.sink.capabilities.partial_text:
            return False
        if text == self._current:
            return True
        common = _common_prefix_length(self._current, text)
        stale_suffix = len(self._current) - common
        new_suffix = text[common:]
        if stale_suffix and not self.sink.backspace(stale_suffix):
            return False
        if new_suffix and not self.sink.insert_text(new_suffix):
            return False
        self._current = text
        self.partial_updates += 1
        return True

    def final(self, text: str) -> bool:
        if self._finished or not self._started:
            return False
        if self.send_partial and self.sink.capabilities.partial_text:
            common = _common_prefix_length(self._current, text)
            stale_suffix = len(self._current) - common
            new_suffix = text[common:]
            if stale_suffix and not self.sink.backspace(stale_suffix):
                return False
            if new_suffix and not self.sink.insert_text(new_suffix):
                return False
        else:
            if text and not self.sink.insert_text(text):
                return False
        if self.final_suffix and not self.sink.insert_text(self.final_suffix):
            return False
        self._current = ""
        self.final_updates += 1
        return True

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.sink.finish()

    def close(self) -> None:
        self.finish()
        self.sink.close()

    def status(self) -> dict[str, Any]:
        return {
            "partialUpdates": self.partial_updates,
            "finalUpdates": self.final_updates,
            "currentPartialLength": len(self._current),
            "sink": self.sink.status(),
        }
