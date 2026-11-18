from __future__ import annotations

import asyncio
import json
import socket
import urllib.request
from typing import Any

import pytest
from websockets.asyncio.client import connect

from tests.helpers import make_config
from voicebridge.protocol import encode_audio_frame
from voicebridge.runtime import BridgeRuntime


async def _ws_until(ws: Any, done: set[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        events.append(message)
        if message.get("type") in done:
            return events


async def _tcp_until(reader: asyncio.StreamReader, done: set[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        assert line
        message = json.loads(line)
        events.append(message)
        if message.get("type") in done:
            return events


@pytest.mark.asyncio
async def test_websocket_tcp_and_http_end_to_end() -> None:
    config = make_config()
    runtime = BridgeRuntime(config)
    await runtime.start()
    try:
        ws_uri = f"ws://127.0.0.1:{config.server.ws_port}/v1/audio"
        async with connect(ws_uri) as ws:
            await ws.send(json.dumps({"type": "hello"}))
            assert (await _ws_until(ws, {"hello_ack"}))[-1]["ok"]
            await ws.send(json.dumps({"type": "start", "sampleRate": 16000}))
            assert (await _ws_until(ws, {"listening"}))[-1]["type"] == "listening"
            for sequence in range(8):
                await ws.send(encode_audio_frame(b"\x00\x00" * 400, sequence=sequence))
            await ws.send(json.dumps({"type": "stop"}))
            events = await _ws_until(ws, {"session_end"})
            assert any(event["type"] == "partial" for event in events)
            final = next(event for event in events if event["type"] == "final")
            assert final["text"] == "你好，世界。"
            assert events[-1]["session"]["firstPartialMs"] is not None

        reader, writer = await asyncio.open_connection("127.0.0.1", config.server.tcp_port)
        try:
            writer.write(b'{"type":"hello"}\n')
            await writer.drain()
            assert (await _tcp_until(reader, {"hello_ack"}))[-1]["type"] == "hello_ack"
            writer.write(b'{"type":"start","sampleRate":16000}\n')
            await writer.drain()
            assert (await _tcp_until(reader, {"listening"}))[-1]["type"] == "listening"
            for sequence in range(8):
                writer.write(encode_audio_frame(b"\x00\x00" * 400, sequence=sequence))
            writer.write(b'{"type":"stop"}\n')
            await writer.drain()
            events = await _tcp_until(reader, {"session_end"})
            assert any(event["type"] == "final" for event in events)
        finally:
            writer.close()
            await writer.wait_closed()

        def fetch(path: str) -> tuple[int, dict[str, Any]]:
            url = f"http://127.0.0.1:{config.server.http_port}{path}"
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status, json.loads(response.read())

        status, health = await asyncio.to_thread(fetch, "/health")
        assert status == 200 and health["ok"]
        status, public = await asyncio.to_thread(fetch, "/v1/status")
        assert status == 200
        assert public["lastSession"]["lastFinal"]["redacted"]
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_udp_discovery_returns_non_secret_metadata() -> None:
    config = make_config(discovery=True)
    runtime = BridgeRuntime(config)
    await runtime.start()
    try:

        def query() -> dict[str, Any]:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3)
            try:
                sock.sendto(
                    b"VOICEBRIDGE_DISCOVER_V1",
                    ("127.0.0.1", config.server.discovery_port),
                )
                data, _ = sock.recvfrom(4096)
                return json.loads(data)
            finally:
                sock.close()

        response = await asyncio.to_thread(query)
        assert response["service"] == "voice-input-bridge"
        assert response["websocketPort"] == config.server.ws_port
        assert "token" not in response
    finally:
        await runtime.close()
