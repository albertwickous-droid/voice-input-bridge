from __future__ import annotations

import sys
from typing import Any

from voicebridge.input.base import InputUnavailable, TextSink
from voicebridge.models import InputCapabilities


class MacOSQuartzSink(TextSink):
    """Injects Unicode into the frontmost macOS app through Quartz CGEvent."""

    capabilities = InputCapabilities(
        partial_text=True,
        backspace=True,
        foreground_guard=True,
        note="Quartz CGEventKeyboardSetUnicodeString; requires Accessibility permission",
    )

    def __init__(self, *, require_same_window: bool = True) -> None:
        if sys.platform != "darwin":
            raise InputUnavailable("MacOSQuartzSink is only available on macOS")
        try:
            import AppKit
            import Quartz
        except ImportError as exc:  # pragma: no cover - platform dependent
            raise InputUnavailable(
                "install the macOS extra: pip install 'voice-input-bridge[macos]'"
            ) from exc
        super().__init__(require_same_window=require_same_window)
        self._AppKit = AppKit
        self._Quartz = Quartz
        self._target_app: str | None = None

    def _frontmost_app(self) -> str:
        workspace = self._AppKit.NSWorkspace.sharedWorkspace()
        application = workspace.frontmostApplication()
        if application is None:
            return ""
        bundle = application.bundleIdentifier()
        return str(bundle or application.localizedName() or "")

    def start(self) -> bool:
        self._target_app = self._frontmost_app()
        self._active = bool(self._target_app)
        self._phase = "ready" if self._active else "error"
        self._error = None if self._active else "no frontmost application"
        return self._active

    def _foreground_is_valid(self) -> bool:
        if not self.require_same_window or self._target_app is None:
            return True
        if self._frontmost_app() == self._target_app:
            return True
        self._mark_paused("frontmost application changed")
        return False

    def insert_text(self, text: str) -> bool:
        if not self._active or not text or not self._foreground_is_valid():
            return not text
        event = self._Quartz.CGEventCreateKeyboardEvent(None, 0, True)
        if event is None:
            self._phase = "error"
            self._error = "could not create Quartz keyboard event"
            return False
        utf16_length = len(text.encode("utf-16-le")) // 2
        self._Quartz.CGEventKeyboardSetUnicodeString(event, utf16_length, text)
        self._Quartz.CGEventPost(self._Quartz.kCGHIDEventTap, event)
        self._inserted_updates += 1
        self._phase = "typing"
        return True

    def _send_key(self, keycode: int) -> bool:
        down = self._Quartz.CGEventCreateKeyboardEvent(None, keycode, True)
        up = self._Quartz.CGEventCreateKeyboardEvent(None, keycode, False)
        if down is None or up is None:
            self._phase = "error"
            self._error = "could not create Quartz key event"
            return False
        self._Quartz.CGEventPost(self._Quartz.kCGHIDEventTap, down)
        self._Quartz.CGEventPost(self._Quartz.kCGHIDEventTap, up)
        return True

    def backspace(self, count: int) -> bool:
        if not self._active or count <= 0 or not self._foreground_is_valid():
            return count <= 0
        for _ in range(count):
            if not self._send_key(51):
                return False
        self._deleted_updates += count
        self._phase = "typing"
        return True

    def status(self) -> dict[str, Any]:
        result = super().status()
        result["targetApplication"] = self._target_app
        return result
