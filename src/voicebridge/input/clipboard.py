from __future__ import annotations

import ctypes
import platform
import shutil
import subprocess
from typing import Any

from voicebridge.input.base import InputUnavailable, TextSink
from voicebridge.models import InputCapabilities


class ClipboardSink(TextSink):
    """Final-only fallback that copies text and sends the platform paste shortcut."""

    capabilities = InputCapabilities(
        partial_text=False,
        backspace=False,
        foreground_guard=False,
        note="final-only clipboard paste fallback",
    )

    def __init__(
        self,
        *,
        require_same_window: bool = True,
        paste_shortcut: str = "auto",
    ) -> None:
        super().__init__(require_same_window=require_same_window)
        self.paste_shortcut = paste_shortcut.strip().lower()
        self.system = platform.system()

    def start(self) -> bool:
        if self.require_same_window:
            self._active = False
            self._phase = "error"
            self._error = (
                "clipboard backend cannot enforce require_same_window; "
                "set input.require_same_window = false explicitly"
            )
            return False
        self._active = True
        self._phase = "ready"
        self._error = None
        return True

    def _copy_windows(self, text: str) -> None:
        if shutil.which("clip") is None:
            raise InputUnavailable("clip.exe was not found")
        subprocess.run(
            ["clip"],
            input=text.encode("utf-16le"),
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _paste_windows(self) -> None:
        if self.paste_shortcut not in {"auto", "ctrl+v"}:
            raise InputUnavailable(
                f"clipboard paste shortcut {self.paste_shortcut!r} is not supported on Windows"
            )
        user32 = ctypes.windll.user32
        user32.keybd_event(0x11, 0, 0, 0)
        user32.keybd_event(0x56, 0, 0, 0)
        user32.keybd_event(0x56, 0, 2, 0)
        user32.keybd_event(0x11, 0, 2, 0)

    def _copy_macos(self, text: str) -> None:
        if shutil.which("pbcopy") is None:
            raise InputUnavailable("pbcopy was not found")
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)

    def _paste_macos(self) -> None:
        if self.paste_shortcut not in {"auto", "cmd+v", "command+v"}:
            raise InputUnavailable(
                f"clipboard paste shortcut {self.paste_shortcut!r} is not supported on macOS"
            )
        if shutil.which("osascript") is None:
            raise InputUnavailable("osascript was not found")
        script = 'tell application "System Events" to keystroke "v" using command down'
        subprocess.run(["osascript", "-e", script], check=True)

    def _copy_linux(self, text: str) -> None:
        command = ["xclip", "-selection", "clipboard"] if shutil.which("xclip") else []
        if not command:
            command = ["xsel", "--clipboard", "--input"] if shutil.which("xsel") else []
        if not command:
            raise InputUnavailable("install xclip or xsel for clipboard support")
        subprocess.run(command, input=text.encode("utf-8"), check=True)

    def _paste_linux(self) -> None:
        if self.paste_shortcut not in {"auto", "ctrl+v"}:
            raise InputUnavailable(
                f"clipboard paste shortcut {self.paste_shortcut!r} is not supported on Linux/X11"
            )
        if shutil.which("xdotool") is None:
            raise InputUnavailable("install xdotool for clipboard paste")
        subprocess.run(["xdotool", "key", "ctrl+v"], check=True)

    def insert_text(self, text: str) -> bool:
        if not self._active or not text:
            return not text
        try:
            if self.system == "Windows":
                self._copy_windows(text)
                self._paste_windows()
            elif self.system == "Darwin":
                self._copy_macos(text)
                self._paste_macos()
            else:
                self._copy_linux(text)
                self._paste_linux()
        except (OSError, subprocess.SubprocessError, InputUnavailable) as exc:
            self._phase = "error"
            self._error = str(exc)
            return False
        self._inserted_updates += 1
        self._phase = "typing"
        return True

    def backspace(self, count: int) -> bool:
        return count <= 0

    def status(self) -> dict[str, Any]:
        result = super().status()
        result["pasteShortcut"] = self.paste_shortcut
        result["platform"] = self.system
        return result
