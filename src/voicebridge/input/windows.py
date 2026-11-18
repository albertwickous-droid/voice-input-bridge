from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes
from typing import Any

from voicebridge.input.base import InputUnavailable, TextSink
from voicebridge.models import InputCapabilities

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_BACK = 0x08

ULONG_PTR = ctypes.c_size_t


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class WindowsSendInputSink(TextSink):
    """Injects Unicode directly through the Win32 SendInput API."""

    capabilities = InputCapabilities(
        partial_text=True,
        backspace=True,
        foreground_guard=True,
        note="Win32 SendInput with KEYEVENTF_UNICODE; no clipboard use",
    )

    def __init__(self, *, require_same_window: bool = True) -> None:
        if __import__("sys").platform != "win32":
            raise InputUnavailable("WindowsSendInputSink is only available on Windows")
        super().__init__(require_same_window=require_same_window)
        expected_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        actual_size = ctypes.sizeof(_INPUT)
        if actual_size != expected_size:
            raise InputUnavailable(
                f"unexpected Windows INPUT size: {actual_size}, expected {expected_size}"
            )
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        ]
        self._user32.SendInput.restype = wintypes.UINT
        self._target_window: int | None = None

    def _current_window(self) -> int:
        return int(self._user32.GetForegroundWindow())

    def start(self) -> bool:
        self._target_window = self._current_window()
        self._active = bool(self._target_window)
        self._phase = "ready" if self._active else "error"
        self._error = None if self._active else "no foreground window"
        return self._active

    def _foreground_is_valid(self) -> bool:
        if not self.require_same_window or self._target_window is None:
            return True
        if self._current_window() == self._target_window:
            return True
        self._mark_paused("foreground window changed")
        return False

    def _send_inputs(self, inputs: list[_INPUT]) -> bool:
        if not inputs:
            return True
        array_type = _INPUT * len(inputs)
        sent = self._user32.SendInput(len(inputs), array_type(*inputs), ctypes.sizeof(_INPUT))
        if sent != len(inputs):
            self._phase = "error"
            self._error = f"SendInput accepted {sent}/{len(inputs)} events"
            return False
        return True

    @staticmethod
    def _key_input(vk: int, scan: int, flags: int) -> _INPUT:
        return _INPUT(
            type=INPUT_KEYBOARD,
            u=_INPUTUNION(
                ki=_KEYBDINPUT(
                    wVk=vk,
                    wScan=scan,
                    dwFlags=flags,
                    time=0,
                    dwExtraInfo=0,
                )
            ),
        )

    def insert_text(self, text: str) -> bool:
        if not self._active or not text or not self._foreground_is_valid():
            return not text
        events: list[_INPUT] = []
        encoded = text.encode("utf-16-le", errors="surrogatepass")
        for (unit,) in struct.iter_unpack("<H", encoded):
            events.append(self._key_input(0, unit, KEYEVENTF_UNICODE))
            events.append(self._key_input(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        if not self._send_inputs(events):
            return False
        self._inserted_updates += 1
        self._phase = "typing"
        return True

    def backspace(self, count: int) -> bool:
        if not self._active or count <= 0 or not self._foreground_is_valid():
            return count <= 0
        events: list[_INPUT] = []
        for _ in range(count):
            events.append(self._key_input(VK_BACK, 0, 0))
            events.append(self._key_input(VK_BACK, 0, KEYEVENTF_KEYUP))
        if not self._send_inputs(events):
            return False
        self._deleted_updates += count
        self._phase = "typing"
        return True

    def status(self) -> dict[str, Any]:
        result = super().status()
        result["targetWindow"] = self._target_window
        return result
