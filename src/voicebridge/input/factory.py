from __future__ import annotations

import importlib
import platform
from typing import Any

from voicebridge.config import InputConfig
from voicebridge.input.base import InputUnavailable, TextSink
from voicebridge.input.clipboard import ClipboardSink
from voicebridge.input.simple import NullSink, StdoutSink


def _plugin_sink(name: str, config: InputConfig) -> TextSink:
    module_name, separator, class_name = name.partition(":")
    if not separator or not module_name or not class_name:
        raise InputUnavailable(f"unknown input backend: {name}")
    module = importlib.import_module(module_name)
    cls: Any = getattr(module, class_name)
    return cls(
        require_same_window=config.require_same_window,
        paste_shortcut=config.paste_shortcut,
    )


def create_text_sink(config: InputConfig) -> TextSink:
    backend = config.backend.lower()
    if backend == "null":
        return NullSink(require_same_window=config.require_same_window)
    if backend == "stdout":
        return StdoutSink(require_same_window=config.require_same_window)
    if backend == "clipboard":
        return ClipboardSink(
            require_same_window=config.require_same_window,
            paste_shortcut=config.paste_shortcut,
        )
    if backend == "windows":
        from voicebridge.input.windows import WindowsSendInputSink

        return WindowsSendInputSink(require_same_window=config.require_same_window)
    if backend == "macos":
        from voicebridge.input.macos import MacOSQuartzSink

        return MacOSQuartzSink(require_same_window=config.require_same_window)
    if backend == "auto":
        system = platform.system()
        if system == "Windows":
            from voicebridge.input.windows import WindowsSendInputSink

            return WindowsSendInputSink(require_same_window=config.require_same_window)
        if system == "Darwin":
            try:
                from voicebridge.input.macos import MacOSQuartzSink

                return MacOSQuartzSink(require_same_window=config.require_same_window)
            except InputUnavailable:
                return ClipboardSink(
                    require_same_window=config.require_same_window,
                    paste_shortcut=config.paste_shortcut,
                )
        return ClipboardSink(
            require_same_window=config.require_same_window,
            paste_shortcut=config.paste_shortcut,
        )
    return _plugin_sink(config.backend, config)
