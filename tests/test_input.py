from __future__ import annotations

import ctypes
import sys

import pytest

from voicebridge.input.base import StreamingTextCommitter, TextSink
from voicebridge.models import InputCapabilities


class RecordingSink(TextSink):
    capabilities = InputCapabilities(partial_text=True, backspace=True, foreground_guard=False)

    def __init__(self) -> None:
        super().__init__()
        self.text = ""
        self.operations: list[tuple[str, str | int]] = []

    def start(self) -> bool:
        self._active = True
        self._phase = "ready"
        return True

    def insert_text(self, text: str) -> bool:
        self.text += text
        self.operations.append(("insert", text))
        self._inserted_updates += 1
        return True

    def backspace(self, count: int) -> bool:
        self.text = self.text[:-count]
        self.operations.append(("backspace", count))
        self._deleted_updates += count
        return True


class FinalOnlySink(RecordingSink):
    capabilities = InputCapabilities(partial_text=False, backspace=False)


def test_partial_revision_applies_minimal_suffix_edits() -> None:
    sink = RecordingSink()
    committer = StreamingTextCommitter(sink)
    assert committer.start()
    assert committer.partial("你好")
    assert committer.partial("你好世界")
    assert committer.final("你好，世界。")
    committer.close()

    assert sink.text == "你好，世界。"
    assert sink.operations == [
        ("insert", "你好"),
        ("insert", "世界"),
        ("backspace", 2),
        ("insert", "，世界。"),
    ]


def test_final_only_sink_skips_partials_and_inserts_final_once() -> None:
    sink = FinalOnlySink()
    committer = StreamingTextCommitter(sink)
    assert committer.start()
    assert not committer.partial("中间结果")
    assert committer.final("最终结果。")
    committer.close()
    assert sink.text == "最终结果。"
    assert sink.operations == [("insert", "最终结果。")]


def test_disabled_partials_insert_final_only() -> None:
    sink = RecordingSink()
    committer = StreamingTextCommitter(sink, send_partial=False)
    assert committer.start()
    assert not committer.partial("中间结果")
    assert committer.final("最终结果。")
    committer.close()
    assert sink.text == "最终结果。"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows INPUT layout check")
def test_windows_input_structure_size() -> None:
    from voicebridge.input.windows import _INPUT

    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(_INPUT) == 40


def test_clipboard_requires_explicit_disable_of_foreground_guard() -> None:
    from voicebridge.input.clipboard import ClipboardSink

    sink = ClipboardSink(require_same_window=True)
    assert not sink.start()
    assert "require_same_window" in str(sink.status()["error"])

    sink = ClipboardSink(require_same_window=False)
    assert sink.start()
    sink.close()
