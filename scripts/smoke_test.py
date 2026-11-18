#!/usr/bin/env python3
"""Start a temporary mock bridge and run WebSocket simulation against it."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def free_port(kind: int = socket.SOCK_STREAM) -> int:
    sock = socket.socket(socket.AF_INET, kind)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def main() -> int:
    http_port, ws_port, tcp_port = free_port(), free_port(), free_port()
    discovery_port = free_port(socket.SOCK_DGRAM)
    with tempfile.TemporaryDirectory(prefix="voicebridge-smoke-") as directory:
        config = Path(directory) / "config.toml"
        config.write_text(
            f"""
[server]
host = "127.0.0.1"
http_host = "127.0.0.1"
http_port = {http_port}
ws_port = {ws_port}
tcp_port = {tcp_port}
discovery_port = {discovery_port}

[transports.websocket]
enabled = true

[transports.tcp]
enabled = true

[transports.serial]
enabled = false

[transports.discovery]
enabled = false

[asr]
provider = "mock"

[asr.mock]
transcript = "smoke test"

[input]
backend = "null"
""",
            encoding="utf-8",
        )
        environment = {**os.environ, "PYTHONUNBUFFERED": "1"}
        process = subprocess.Popen(
            [sys.executable, "-m", "voicebridge", "serve", "--config", str(config)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        try:
            deadline = time.monotonic() + 10
            health = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=5)
                    raise RuntimeError(
                        f"service exited early ({process.returncode})\n{stdout}\n{stderr}"
                    )
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{http_port}/health", timeout=1
                    ) as response:
                        health = json.loads(response.read())
                    break
                except OSError:
                    time.sleep(0.1)
            if health is None or not health.get("ok"):
                raise RuntimeError(f"health check failed: {health}")

            simulated = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "voicebridge",
                    "simulate",
                    "--target",
                    f"ws://127.0.0.1:{ws_port}/v1/audio",
                    "--seconds",
                    "0.4",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            if simulated.returncode != 0:
                raise RuntimeError(
                    f"simulation failed ({simulated.returncode})\n"
                    f"{simulated.stdout}\n{simulated.stderr}"
                )
            events = json.loads(simulated.stdout)
            types = {event.get("type") for event in events}
            if not {"hello_ack", "listening", "final", "session_end"}.issubset(types):
                raise RuntimeError(f"unexpected event types: {sorted(types)}")
            print("Smoke test passed:", ", ".join(sorted(types)))
            return 0
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            stdout, stderr = process.communicate()
            if process.returncode not in {0, 1, -15, 143}:
                print(stdout, file=sys.stderr)
                print(stderr, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
