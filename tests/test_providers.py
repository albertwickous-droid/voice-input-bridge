from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

from voicebridge.models import AudioFormat
from voicebridge.providers.aliyun import AliyunParaformerProvider
from voicebridge.providers.base import ProviderError, ProviderRequest, ProviderUnavailable
from voicebridge.providers.command import CommandProvider
from voicebridge.providers.deepgram import DeepgramProvider
from voicebridge.providers.mock import MockProvider


async def _audio(*chunks: bytes):
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_mock_provider_emits_partials_and_final() -> None:
    provider = MockProvider()
    request = ProviderRequest(
        session_id="test",
        audio=_audio(b"a" * 3_200, b"b" * 3_200),
        audio_format=AudioFormat(),
        options={"partial_words": ["第一", "第一第二"], "transcript": "第一第二。"},
    )
    events = [event async for event in provider.stream(request)]
    assert [event.final for event in events] == [False, False, True]
    assert events[-1].text == "第一第二。"


def test_aliyun_event_parser() -> None:
    partial = {
        "payload": {
            "output": {
                "sentence": {
                    "text": "你好",
                    "begin_time": 10,
                    "end_time": None,
                    "sentence_end": False,
                }
            }
        }
    }
    final = {
        "payload": {
            "output": {
                "sentence": {
                    "text": "你好，世界。",
                    "begin_time": 10,
                    "end_time": 900,
                    "sentence_end": True,
                }
            }
        }
    }
    partial_event = AliyunParaformerProvider._parse_event(partial)
    final_event = AliyunParaformerProvider._parse_event(final)
    assert partial_event is not None and not partial_event.final
    assert final_event is not None and final_event.final
    assert AliyunParaformerProvider._parse_event({"payload": {"output": {}}}) is None


@pytest.mark.asyncio
async def test_deepgram_requires_api_key_before_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    provider = DeepgramProvider()
    request = ProviderRequest(
        session_id="test",
        audio=_audio(),
        audio_format=AudioFormat(),
        options={},
    )
    with pytest.raises(ProviderUnavailable, match="DEEPGRAM_API_KEY"):
        async for _ in provider.stream(request):
            pass


def test_deepgram_result_parser() -> None:
    result = DeepgramProvider._parse_result(
        {
            "type": "Results",
            "duration": 0.5,
            "is_final": True,
            "speech_final": True,
            "channel": {"alternatives": [{"transcript": "你好世界", "confidence": 0.98}]},
        }
    )
    assert result is not None
    assert result.final
    assert result.text == "你好世界"
    assert result.confidence == pytest.approx(0.98)


@pytest.mark.asyncio
async def test_command_provider_reads_wav_and_returns_stdout(tmp_path: Path) -> None:
    script = tmp_path / "fake_asr.py"
    script.write_text(
        "import sys, wave\n"
        "with wave.open(sys.argv[1], 'rb') as wav:\n"
        "    assert wav.getnchannels() == 1\n"
        "    assert wav.getframerate() == 16000\n"
        "print('命令识别结果。')\n",
        encoding="utf-8",
    )
    provider = CommandProvider()
    request = ProviderRequest(
        session_id="test",
        audio=_audio(b"\x00\x00" * 1_600),
        audio_format=AudioFormat(),
        options={"command": [sys.executable, str(script), "{wav}"], "timeout_seconds": 20},
    )
    events = [event async for event in provider.stream(request)]
    assert len(events) == 1
    assert events[0].final
    assert events[0].text == "命令识别结果。"


@pytest.mark.asyncio
async def test_aliyun_provider_preserves_event_order_with_fake_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSession:
        def start(self) -> None:
            pass

        def events(self):
            yield {
                "payload": {
                    "output": {
                        "sentence": {
                            "text": "你好",
                            "begin_time": 0,
                            "sentence_end": False,
                        }
                    }
                }
            }
            yield {
                "payload": {
                    "output": {
                        "sentence": {
                            "text": "你好，世界。",
                            "begin_time": 0,
                            "end_time": 900,
                            "sentence_end": True,
                        }
                    }
                }
            }

        def send_audio_frame(self, chunk: bytes) -> None:
            del chunk

        def stop(self) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            del kwargs
            self.audio = self
            self.asr = self

        def recognize(self, **kwargs):
            del kwargs
            return FakeSession()

        def close(self) -> None:
            pass

    fake_module = types.ModuleType("dashscope")
    fake_module.Client = FakeClient
    monkeypatch.setitem(sys.modules, "dashscope", fake_module)
    provider = AliyunParaformerProvider()
    request = ProviderRequest(
        session_id="test",
        audio=_audio(b"\x00\x00" * 100),
        audio_format=AudioFormat(),
        options={"api_key": "test-key", "final_timeout_seconds": 2},
    )
    events = [event async for event in provider.stream(request)]
    assert [event.final for event in events] == [False, True]
    assert events[-1].text == "你好，世界。"


async def _endless_audio():
    while True:
        yield b"\x00\x00" * 1_600
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_aliyun_provider_error_does_not_wait_for_unfinished_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingSession:
        def start(self) -> None:
            raise RuntimeError("upstream failed")

        def close(self) -> None:
            pass

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            del kwargs
            self.audio = self
            self.asr = self

        def recognize(self, **kwargs):
            del kwargs
            return FailingSession()

        def close(self) -> None:
            pass

    fake_module = types.ModuleType("dashscope")
    fake_module.Client = FakeClient
    monkeypatch.setitem(sys.modules, "dashscope", fake_module)
    provider = AliyunParaformerProvider()
    request = ProviderRequest(
        session_id="test",
        audio=_endless_audio(),
        audio_format=AudioFormat(),
        options={"api_key": "test-key", "final_timeout_seconds": 2},
    )

    async def consume() -> None:
        async for _ in provider.stream(request):
            pass

    with pytest.raises(ProviderError, match="upstream failed"):
        await asyncio.wait_for(consume(), timeout=1)


@pytest.mark.asyncio
async def test_deepgram_error_does_not_wait_for_unfinished_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import websockets.asyncio.client as websockets_client

    class FailingWebSocket:
        def __init__(self) -> None:
            self.sent_error = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.sent_error:
                self.sent_error = True
                return json.dumps({"type": "Error", "description": "upstream failed"})
            raise StopAsyncIteration

        async def send(self, data: bytes | str) -> None:
            del data
            await asyncio.sleep(0)

    monkeypatch.setattr(
        websockets_client,
        "connect",
        lambda *args, **kwargs: FailingWebSocket(),
    )
    provider = DeepgramProvider()
    request = ProviderRequest(
        session_id="test",
        audio=_endless_audio(),
        audio_format=AudioFormat(),
        options={"api_key": "test-key", "final_timeout_seconds": 2},
    )

    async def consume() -> None:
        async for _ in provider.stream(request):
            pass

    with pytest.raises(ProviderError, match="upstream failed"):
        await asyncio.wait_for(consume(), timeout=1)
