from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import math
import os
import platform
import signal
import socket
import struct
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from voicebridge import __version__
from voicebridge.config import BridgeConfig, ConfigError, load_config
from voicebridge.logging_utils import configure_logging
from voicebridge.protocol import encode_audio_frame
from voicebridge.providers.registry import available_providers
from voicebridge.runtime import BridgeRuntime

_SECRET_KEY_PARTS = ("token", "api_key", "apikey", "secret", "password", "credential")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voicebridge",
        description="Device-agnostic real-time speech-to-text bridge.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def config_argument(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--config",
            type=Path,
            help="TOML configuration file (default: ./config.toml or VOICEBRIDGE_CONFIG)",
        )

    serve = sub.add_parser("serve", help="start HTTP, WebSocket, TCP, serial, and discovery services")
    config_argument(serve)

    doctor = sub.add_parser("doctor", help="check installation, configuration, credentials, and ports")
    config_argument(doctor)
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    simulate = sub.add_parser("simulate", help="send synthetic PCM through a local WebSocket or TCP endpoint")
    simulate.add_argument(
        "--target",
        default="ws://127.0.0.1:18766/v1/audio",
        help="ws:// URL or tcp://host:port",
    )
    simulate.add_argument("--token", default=os.environ.get("VOICEBRIDGE_TOKEN", ""))
    simulate.add_argument("--seconds", type=float, default=0.8)
    simulate.add_argument("--timeout", type=float, default=15.0)

    config = sub.add_parser("config", help="print the effective configuration with secrets redacted")
    config_argument(config)
    config.add_argument("--json", action="store_true", help="emit JSON instead of TOML-like text")

    providers = sub.add_parser("providers", help="list built-in and installed ASR providers")
    providers.add_argument("--json", action="store_true")
    return parser


def _run_serve(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    configure_logging(config.logging)

    async def run() -> int:
        runtime = BridgeRuntime(config)
        await runtime.start()
        statuses = runtime.transport_snapshots()
        print(
            f"voice-input-bridge {__version__} | provider={config.asr.provider} "
            f"| HTTP=http://{config.server.http_host}:{config.server.http_port}"
        )
        print(
            f"WebSocket=ws://{config.server.host}:{config.server.ws_port}"
            f"{config.transports.websocket.path} | TCP={config.server.host}:{config.server.tcp_port}"
        )
        for name, status in statuses.items():
            if status.get("error"):
                print(f"{name}: {status['state']} ({status['error']})", file=sys.stderr)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signame in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(signame, stop.set)
        try:
            await stop.wait()
        finally:
            await runtime.close()
        return 0

    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 130


def _redact(value: Any, key: str = "") -> Any:
    lowered = key.lower()
    if isinstance(value, dict):
        return {item_key: _redact(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if any(part in lowered for part in _SECRET_KEY_PARTS) and isinstance(value, str):
        return "<configured>" if value else ""
    if isinstance(value, Path):
        return str(value)
    return value


def _config_dict(config: BridgeConfig) -> dict[str, Any]:
    return _redact(asdict(config))


def _port_available(host: str, port: int) -> tuple[bool, str | None]:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError as exc:
        return False, str(exc)
    finally:
        sock.close()
    return True, None


def _credential_configured(config: BridgeConfig, key: str, env_name: str) -> bool:
    return bool(str(config.asr.options.get(key) or os.environ.get(env_name, "")).strip())


def _run_doctor(args: argparse.Namespace, *, as_json: bool) -> int:
    config = load_config(args.config)
    checks: list[dict[str, Any]] = []

    def add(
        check: str,
        status: str,
        detail: str,
        *,
        severity: str = "error",
    ) -> None:
        checks.append(
            {"check": check, "status": status, "severity": severity, "detail": detail}
        )

    add("platform", "pass", f"{platform.system()} {platform.release()} ({platform.machine()})")
    add("python", "pass", platform.python_version())
    add(
        "websockets",
        "pass" if importlib.util.find_spec("websockets") else "fail",
        "installed" if importlib.util.find_spec("websockets") else "install websockets>=13.1",
    )

    if config.transports.serial.enabled:
        installed = importlib.util.find_spec("serial") is not None
        add("pyserial", "pass" if installed else "fail", "installed" if installed else "install the serial extra")
    if config.asr.provider == "aliyun":
        installed = importlib.util.find_spec("dashscope") is not None
        add(
            "dashscope",
            "pass" if installed else "fail",
            "installed" if installed else "install the Aliyun extra",
        )
        key = _credential_configured(config, "api_key", "DASHSCOPE_API_KEY")
        add("aliyun credentials", "pass" if key else "fail", "API key configured" if key else "DASHSCOPE_API_KEY is missing")
    elif config.asr.provider == "deepgram":
        key = _credential_configured(config, "api_key", "DEEPGRAM_API_KEY")
        add("deepgram credentials", "pass" if key else "fail", "API key configured" if key else "DEEPGRAM_API_KEY is missing")
    elif config.asr.provider == "command":
        command = config.asr.options.get("command")
        add(
            "command provider",
            "pass" if command else "fail",
            "command configured" if command else "asr.command.command is missing",
        )
    elif config.asr.provider == "mock":
        add("ASR provider", "pass", "mock provider needs no credentials")
    elif config.asr.provider in available_providers():
        add("ASR provider", "warn", f"plugin '{config.asr.provider}' is installed; initialize it before use", severity="warning")
    else:
        add("ASR provider", "fail", f"provider '{config.asr.provider}' is not installed")

    try:
        from voicebridge.input.factory import create_text_sink

        sink = create_text_sink(config.input)
        started = sink.start()
        detail = sink.status()
        sink.close()
        add(
            "text input backend",
            "pass" if started else "fail",
            f"{detail.get('backend')}: {'ready' if started else detail.get('error') or 'not ready'}",
        )
    except Exception as exc:
        add("text input backend", "fail", f"{exc.__class__.__name__}: {exc}")

    endpoints = {
        ("http", config.server.http_host, config.server.http_port),
        ("websocket", config.server.host, config.server.ws_port),
        ("tcp", config.server.host, config.server.tcp_port),
    }
    if config.transports.discovery.enabled:
        endpoints.add(("discovery(udp)", config.server.host, config.server.discovery_port))
    for name, host, port in sorted(endpoints):
        if name.startswith("discovery"):
            add(name, "warn", "UDP port occupancy is not checked by doctor", severity="warning")
            continue
        available, error = _port_available(host, port)
        add(name, "pass" if available else "fail", f"{host}:{port} available" if available else f"{host}:{port} unavailable: {error}")

    if config.server.require_token and not config.server.token:
        add(
            "token",
            "fail",
            "require_token is true but token is empty; every client will be rejected",
        )
    else:
        add(
            "token",
            "pass",
            "configured" if config.server.token else "not configured (not required)",
        )
    for warning in config.validate():
        add("configuration warning", "warn", warning, severity="warning")

    failed = any(item["status"] == "fail" for item in checks)
    payload = {
        "ok": not failed,
        "version": __version__,
        "config": str(config.source_path) if config.source_path else None,
        "provider": config.asr.provider,
        "inputBackend": config.input.backend,
        "checks": checks,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            marker = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}[item["status"]]
            print(f"[{marker:4}] {item['check']}: {item['detail']}")
        print("Doctor result:", "PASS" if not failed else "FAIL")
    return 0 if not failed else 1


def _sine_pcm(seconds: float, sample_rate: int = 16_000) -> bytes:
    count = max(1, int(seconds * sample_rate))
    samples = bytearray()
    for index in range(count):
        value = int(0.08 * 32767 * math.sin(2 * math.pi * 440 * index / sample_rate))
        samples.extend(struct.pack("<h", value))
    return bytes(samples)


async def _receive_json_until(ws: Any, done: set[str], timeout: float) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        if isinstance(raw, bytes):
            continue
        message = json.loads(raw)
        if not isinstance(message, dict):
            continue
        events.append(message)
        if message.get("type") in done:
            return events


async def _simulate_ws(target: str, token: str, seconds: float, timeout: float) -> list[dict[str, Any]]:
    from websockets.asyncio.client import connect

    events: list[dict[str, Any]] = []
    async with connect(target, max_size=1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "hello", "token": token}, ensure_ascii=False))
        events.extend(await _receive_json_until(ws, {"hello_ack", "error"}, timeout))
        if events[-1].get("type") == "error":
            return events
        await ws.send(
            json.dumps(
                {
                    "type": "start",
                    "sampleRate": 16000,
                    "channels": 1,
                    "bitsPerSample": 16,
                    "encoding": "pcm_s16le",
                    "language": "zh-CN",
                }
            )
        )
        events.extend(await _receive_json_until(ws, {"listening", "error"}, timeout))
        if events[-1].get("type") == "error":
            return events
        pcm = _sine_pcm(seconds)
        for sequence, offset in enumerate(range(0, len(pcm), 640)):
            await ws.send(encode_audio_frame(pcm[offset : offset + 640], sequence=sequence))
        await ws.send(json.dumps({"type": "stop"}))
        events.extend(await _receive_json_until(ws, {"session_end", "error"}, timeout))
    return events


async def _simulate_tcp(target: str, token: str, seconds: float, timeout: float) -> list[dict[str, Any]]:
    parsed = urlsplit(target)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 18767
    reader, writer = await asyncio.open_connection(host, port)
    events: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        writer.write((json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        await writer.drain()

    async def receive_until(done: set[str]) -> None:
        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout=timeout)
            if not raw:
                raise RuntimeError("TCP connection closed")
            message = json.loads(raw)
            events.append(message)
            if message.get("type") in done:
                return

    try:
        await send({"type": "hello", "token": token})
        await receive_until({"hello_ack", "error"})
        if events[-1].get("type") == "error":
            return events
        await send(
            {
                "type": "start",
                "sampleRate": 16000,
                "channels": 1,
                "bitsPerSample": 16,
                "encoding": "pcm_s16le",
                "language": "zh-CN",
            }
        )
        await receive_until({"listening", "error"})
        if events[-1].get("type") == "error":
            return events
        pcm = _sine_pcm(seconds)
        for sequence, offset in enumerate(range(0, len(pcm), 640)):
            writer.write(encode_audio_frame(pcm[offset : offset + 640], sequence=sequence))
        await send({"type": "stop"})
        await receive_until({"session_end", "error"})
    finally:
        writer.close()
        await writer.wait_closed()
    return events


def _run_simulate(args: argparse.Namespace) -> int:
    if args.seconds <= 0:
        raise ConfigError("--seconds must be greater than zero")
    target = args.target
    if target.startswith(("ws://", "wss://")):
        events = asyncio.run(_simulate_ws(target, args.token, args.seconds, args.timeout))
    elif target.startswith("tcp://"):
        events = asyncio.run(_simulate_tcp(target, args.token, args.seconds, args.timeout))
    else:
        raise ConfigError("--target must start with ws://, wss://, or tcp://")
    print(json.dumps(events, ensure_ascii=False, indent=2))
    return 0 if not any(event.get("type") == "error" for event in events) else 1


def _toml_like(value: Any, prefix: str = "") -> list[str]:
    lines: list[str] = []
    scalar_items = [
        (key, item)
        for key, item in value.items()
        if not isinstance(item, dict) and item is not None
    ]
    table_items = [(key, item) for key, item in value.items() if isinstance(item, dict)]
    if scalar_items and prefix:
        lines.append(f"[{prefix}]")
    for key, item in scalar_items:
        lines.append(f"{key} = {json.dumps(item, ensure_ascii=False)}")
    if scalar_items and table_items:
        lines.append("")
    for key, item in table_items:
        child = f"{prefix}.{key}" if prefix else key
        lines.extend(_toml_like(item, child))
        if lines and lines[-1] != "":
            lines.append("")
    return lines


def _run_config(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    payload = _config_dict(config)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("\n".join(_toml_like(payload)).rstrip())
    return 0


def _run_providers(args: argparse.Namespace) -> int:
    providers = available_providers()
    if args.json:
        print(json.dumps(providers, ensure_ascii=False, indent=2))
    else:
        for name, detail in sorted(providers.items()):
            print(f"{name}: {detail}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            return _run_serve(args)
        if args.command == "doctor":
            return _run_doctor(args, as_json=args.json)
        if args.command == "simulate":
            return _run_simulate(args)
        if args.command == "config":
            return _run_config(args)
        if args.command == "providers":
            return _run_providers(args)
    except (ConfigError, OSError, RuntimeError) as exc:
        print(f"voicebridge: {exc}", file=sys.stderr)
        return 2
    return 2
