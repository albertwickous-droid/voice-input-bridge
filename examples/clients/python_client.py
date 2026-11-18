#!/usr/bin/env python3
"""Example WebSocket/TCP client for Voice Input Bridge.

Examples:
    python examples/clients/python_client.py --target ws://127.0.0.1:18766/v1/audio --wav speech.wav
    python examples/clients/python_client.py --target tcp://127.0.0.1:18767 --microphone --seconds 5
    cat raw.pcm | python examples/clients/python_client.py --target ws://127.0.0.1:18766/v1/audio
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import queue
import sys
import time
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from voicebridge.protocol import encode_audio_frame

SAMPLE_RATE = 16_000
CHANNELS = 1
BITS = 16
CHUNK_BYTES = 640  # 20 ms


def _print_event(message: dict[str, Any]) -> None:
    print(json.dumps(message, ensure_ascii=False), flush=True)


async def _paced_chunks(
    chunks: AsyncIterator[bytes], *, realtime: bool, chunk_bytes: int
) -> AsyncIterator[bytes]:
    async for chunk in chunks:
        yield chunk
        if realtime:
            await asyncio.sleep(len(chunk) / (SAMPLE_RATE * CHANNELS * (BITS // 8)))


async def _from_wav(path: Path) -> AsyncIterator[bytes]:
    with wave.open(str(path), "rb") as wav:
        if (
            wav.getnchannels() != CHANNELS
            or wav.getsampwidth() != BITS // 8
            or wav.getframerate() != SAMPLE_RATE
        ):
            raise ValueError("WAV must be mono, 16-bit PCM, 16 kHz")
        while data := wav.readframes(320):
            yield data


async def _from_stdin() -> AsyncIterator[bytes]:
    loop = asyncio.get_running_loop()
    while data := await loop.run_in_executor(None, sys.stdin.buffer.read, CHUNK_BYTES):
        yield data


async def _from_microphone(seconds: float) -> AsyncIterator[bytes]:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("microphone mode requires: pip install sounddevice") from exc

    captured: queue.Queue[bytes] = queue.Queue(maxsize=100)

    def callback(indata: Any, frames: int, timing: Any, status: Any) -> None:
        del frames, timing
        if status:
            print(f"microphone status: {status}", file=sys.stderr)
        with contextlib.suppress(queue.Full):
            captured.put_nowait(bytes(indata))

    stream = sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        blocksize=CHUNK_BYTES // 2,
        callback=callback,
    )
    deadline = time.monotonic() + seconds
    stream.start()
    try:
        while time.monotonic() < deadline:
            try:
                yield await asyncio.to_thread(captured.get, True, 0.25)
            except queue.Empty:
                continue
    finally:
        stream.stop()
        stream.close()


async def _audio_source(
    *, wav_path: Path | None, microphone_seconds: float | None, realtime: bool
) -> AsyncIterator[bytes]:
    if wav_path is not None:
        source: AsyncIterator[bytes] = _from_wav(wav_path)
    elif microphone_seconds is not None:
        source = _from_microphone(microphone_seconds)
    elif not sys.stdin.isatty():
        source = _from_stdin()
    else:
        raise ValueError("provide --wav, --microphone with --seconds, or pipe raw PCM on stdin")
    async for chunk in _paced_chunks(source, realtime=realtime, chunk_bytes=CHUNK_BYTES):
        yield chunk


async def _ws_receive(ws: Any) -> None:
    while True:
        raw = await ws.recv()
        if isinstance(raw, bytes):
            continue
        message = json.loads(raw)
        _print_event(message)
        if message.get("type") in {"session_end", "error"}:
            return


async def _run_websocket(args: argparse.Namespace) -> int:
    from websockets.asyncio.client import connect

    async with connect(args.target, max_size=1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "hello", "token": args.token}))
        while True:
            message = json.loads(await ws.recv())
            _print_event(message)
            if message.get("type") == "hello_ack":
                break
            if message.get("type") == "error":
                return 1
        await ws.send(
            json.dumps(
                {
                    "type": "start",
                    "sampleRate": SAMPLE_RATE,
                    "channels": CHANNELS,
                    "bitsPerSample": BITS,
                    "encoding": "pcm_s16le",
                    "language": args.language,
                }
            )
        )
        while True:
            message = json.loads(await ws.recv())
            _print_event(message)
            if message.get("type") in {"listening", "error"}:
                if message.get("type") == "error":
                    return 1
                break
        receiver = asyncio.create_task(_ws_receive(ws))
        sequence = 0
        async for chunk in _audio_source(
            wav_path=args.wav,
            microphone_seconds=args.seconds if args.microphone else None,
            realtime=not args.no_realtime,
        ):
            await ws.send(encode_audio_frame(chunk, sequence=sequence))
            sequence = (sequence + 1) & 0xFFFF
        await ws.send(json.dumps({"type": "stop"}))
        await receiver
    return 0


async def _tcp_readline(reader: asyncio.StreamReader) -> dict[str, Any]:
    line = await reader.readline()
    if not line:
        raise RuntimeError("server closed the TCP connection")
    value = json.loads(line)
    _print_event(value)
    return value


async def _tcp_receive(reader: asyncio.StreamReader) -> None:
    while True:
        message = await _tcp_readline(reader)
        if message.get("type") in {"session_end", "error"}:
            return


async def _run_tcp(args: argparse.Namespace) -> int:
    target = urlsplit(args.target)
    reader, writer = await asyncio.open_connection(
        target.hostname or "127.0.0.1", target.port or 18767
    )

    async def send_json(message: dict[str, Any]) -> None:
        writer.write(
            (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        )
        await writer.drain()

    try:
        await send_json({"type": "hello", "token": args.token})
        while True:
            message = await _tcp_readline(reader)
            if message.get("type") == "hello_ack":
                break
            if message.get("type") == "error":
                return 1
        await send_json(
            {
                "type": "start",
                "sampleRate": SAMPLE_RATE,
                "channels": CHANNELS,
                "bitsPerSample": BITS,
                "encoding": "pcm_s16le",
                "language": args.language,
            }
        )
        while True:
            message = await _tcp_readline(reader)
            if message.get("type") in {"listening", "error"}:
                if message.get("type") == "error":
                    return 1
                break
        receiver = asyncio.create_task(_tcp_receive(reader))
        sequence = 0
        async for chunk in _audio_source(
            wav_path=args.wav,
            microphone_seconds=args.seconds if args.microphone else None,
            realtime=not args.no_realtime,
        ):
            writer.write(encode_audio_frame(chunk, sequence=sequence))
            sequence = (sequence + 1) & 0xFFFF
        await send_json({"type": "stop"})
        await receiver
    finally:
        writer.close()
        await writer.wait_closed()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="ws://127.0.0.1:18766/v1/audio")
    parser.add_argument("--token", default="")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--wav", type=Path)
    parser.add_argument("--microphone", action="store_true")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument(
        "--no-realtime", action="store_true", help="send pre-recorded audio as fast as possible"
    )
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    if not args.target.startswith(("ws://", "wss://", "tcp://")):
        raise ValueError("--target must start with ws://, wss://, or tcp://")
    if args.microphone and args.wav:
        raise ValueError("choose either --microphone or --wav")
    if args.target.startswith(("ws://", "wss://")):
        return await _run_websocket(args)
    return await _run_tcp(args)


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(_main_async(args))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"client: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
