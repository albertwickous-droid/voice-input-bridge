from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.helpers import make_config
from voicebridge.connection import ConnectionRejected, ConnectionSession
from voicebridge.models import AudioFormat
from voicebridge.service import SessionHandle, VoiceBridgeService


class EventCollector:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, message: dict[str, Any]) -> None:
        self.events.append(message)


@pytest.mark.asyncio
async def test_service_streams_partial_and_final_through_null_sink() -> None:
    config = make_config()
    service = VoiceBridgeService(config)
    collector = EventCollector()
    handle = await service.begin_session(AudioFormat(), emit=collector)
    await asyncio.sleep(0)
    await handle.push(b"\x00\x00" * 2_000)
    status = await service.stop(handle)
    await service.close()

    types = [event["type"] for event in collector.events]
    assert "partial" in types
    assert "final" in types
    assert types[-1] == "session_end"
    assert status.state == "completed"
    assert status.first_partial_ms is not None
    assert status.last_final == "你好，世界。"


@pytest.mark.asyncio
async def test_session_byte_limit_counts_truncated_and_dropped_audio() -> None:
    config = make_config(max_audio_seconds=0.1)
    service = VoiceBridgeService(config)
    handle = await service.begin_session(AudioFormat(), emit=EventCollector())
    assert await handle.push(b"x" * 10_000)
    assert handle.status.bytes_received == 3_200
    assert handle.status.dropped_bytes == 6_800
    await service.stop(handle)
    await service.close()


@pytest.mark.asyncio
async def test_connection_session_requires_valid_token() -> None:
    config = make_config(require_token=True, token="correct")
    service = VoiceBridgeService(config)
    messages: list[dict[str, Any]] = []

    async def send_json(message: dict[str, Any]) -> None:
        messages.append(message)

    connection = ConnectionSession(service, send_json)
    with pytest.raises(ConnectionRejected):
        await connection.handle_control({"type": "hello", "token": "wrong"})
    assert messages[-1]["code"] == "unauthorized"

    accepted = ConnectionSession(service, send_json)
    await accepted.handle_control({"type": "hello", "token": "correct"})
    assert messages[-1]["type"] == "hello_ack"

@pytest.mark.asyncio
async def test_session_stop_does_not_block_on_full_audio_queue() -> None:
    config = make_config()
    service = VoiceBridgeService(config)
    handle = SessionHandle(
        service,
        session_id="full-queue",
        audio_format=AudioFormat(),
        language="zh-CN",
        emit=EventCollector(),
    )
    for _ in range(handle.audio_queue.maxsize):
        handle.audio_queue.put_nowait(b"1234")

    await asyncio.wait_for(handle.stop(), timeout=0.1)

    assert handle.status.state == "finishing"
    assert handle.status.dropped_bytes == handle.audio_queue.maxsize * 4
    assert handle.audio_queue.qsize() == 1
    assert handle.audio_queue.get_nowait() is None
