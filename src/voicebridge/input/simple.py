from __future__ import annotations

import sys
from typing import Any

from voicebridge.input.base import TextSink
from voicebridge.models import InputCapabilities


class NullSink(TextSink):
    capabilities = InputCapabilities(
        partial_text=True,
        backspace=True,
        foreground_guard=False,
        note="captures text without touching the OS",
    )

    def __init__(self, *, require_same_window: bool = True) -> None:
        super().__init__(require_same_window=require_same_window)
        self.text = ""

    def start(self) -> bool:
        self._active = True
        self._phase = "ready"
        return True

    def insert_text(self, text: str) -> bool:
        if not self._active:
            return False
        self.text += text
        self._inserted_updates += 1
        return True

    def backspace(self, count: int) -> bool:
        if not self._active:
            return False
        self.text = self.text[:-count] if count > 0 else self.text
        self._deleted_updates += count
        return True

    def finish(self) -> None:
        super().finish()
        self._phase = "captured"

    def status(self) -> dict[str, Any]:
        result = super().status()
        result["capturedText"] = self.text
        return result


class StdoutSink(TextSink):
    capabilities = InputCapabilities(
        partial_text=True,
        backspace=True,
        foreground_guard=False,
        note="writes incremental edits to stdout",
    )

    def __init__(self, *, require_same_window: bool = True) -> None:
        super().__init__(require_same_window=require_same_window)

    def start(self) -> bool:
        self._active = True
        self._phase = "ready"
        return True

    def insert_text(self, text: str) -> bool:
        if not self._active:
            return False
        sys.stdout.write(text)
        sys.stdout.flush()
        self._inserted_updates += 1
        return True

    def backspace(self, count: int) -> bool:
        if not self._active:
            return False
        sys.stdout.write("\b \b" * max(0, count))
        sys.stdout.flush()
        self._deleted_updates += count
        return True
