from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from voicebridge.config import BridgeConfig
from voicebridge.connection import ConnectionRejected, ConnectionSession
from voicebridge.protocol import ProtocolError, StreamDecoder, encode_control
from voicebridge.service import VoiceBridgeService

_PREFERRED_VIDS = {0x303A, 0x2341, 0x2E8A, 0x1A86, 0x10C4, 0x239A}


class SerialTransport:
    """Reconnecting USB CDC/ACM transport backed by optional pyserial."""

    name = "serial"

    def __init__(self, config: BridgeConfig, service: VoiceBridgeService) -> None:
        self.config = config
        self.service = service
        self._serial_module: Any = None
        self._list_ports: Any = None
        self._task: asyncio.Task[None] | None = None
        self._serial: Any = None
        self._closing = False
        self._state = "stopped"
        self._error: str | None = None
        self._resolved_port: str | None = None

    async def start(self) -> bool:
        if not self.config.transports.serial.enabled:
            self._state = "disabled"
            return True
        try:
            import serial
            from serial.tools import list_ports
        except ImportError:
            self._state = "error"
            self._error = "install the serial extra: pip install 'voice-input-bridge[serial]'"
            return False
        self._serial_module = serial
        self._list_ports = list_ports
        self._closing = False
        self._state = "waiting"
        self._task = asyncio.create_task(self._connection_loop(), name="voicebridge-serial")
        return True

    def _resolve_port(self) -> str:
        configured = self.config.transports.serial.port.strip()
        if configured.lower() != "auto":
            return configured
        candidates = list(self._list_ports.comports())
        if not candidates:
            raise RuntimeError("no serial ports found")
        candidates.sort(
            key=lambda item: (
                0 if getattr(item, "vid", None) in _PREFERRED_VIDS else 1,
                0 if "usb" in str(getattr(item, "hwid", "")).lower() else 1,
                str(item.device),
            )
        )
        selected = candidates[0]
        description = " ".join(
            part
            for part in (
                getattr(selected, "description", ""),
                getattr(selected, "manufacturer", ""),
                getattr(selected, "hwid", ""),
            )
            if part
        )
        if (
            getattr(selected, "vid", None) not in _PREFERRED_VIDS
            and "usb" not in description.lower()
        ):
            raise RuntimeError("no likely USB serial device found")
        return str(selected.device)

    async def _connection_loop(self) -> None:
        while not self._closing:
            serial_port: Any = None
            try:
                self._state = "waiting"
                port = self._resolve_port()
                self._resolved_port = port
                serial_port = await asyncio.to_thread(
                    self._serial_module.Serial,
                    port,
                    self.config.transports.serial.baudrate,
                    timeout=0.2,
                    write_timeout=2,
                )
                self._serial = serial_port
                self._state = "connected"
                self._error = None
                await self._run_connection(serial_port)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._closing:
                    self._state = "waiting"
                    self._error = f"{exc.__class__.__name__}: {exc}"
            finally:
                self._serial = None
                if serial_port is not None:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(serial_port.close)
            if not self._closing:
                await asyncio.sleep(1.0)

    async def _run_connection(self, serial_port: Any) -> None:
        outbound: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)
        decoder = StreamDecoder(strict=True)
        closed = asyncio.Event()
        write_lock = asyncio.Lock()

        async def send_json(message: dict[str, Any]) -> None:
            if closed.is_set():
                return
            payload = encode_control(message)
            try:
                outbound.put_nowait(payload)
            except asyncio.QueueFull:
                raise RuntimeError("serial outbound queue is full") from None

        connection = ConnectionSession(self.service, send_json)

        async def writer() -> None:
            while True:
                payload = await outbound.get()
                if payload is None:
                    return
                async with write_lock:
                    await asyncio.to_thread(serial_port.write, payload)
                    await asyncio.to_thread(serial_port.flush)

        async def reader() -> None:
            while True:
                chunk = await asyncio.to_thread(serial_port.read, 4096)
                if not chunk:
                    continue
                for item in decoder.feed(chunk):
                    if hasattr(item, "value"):
                        await connection.handle_control(item.value)
                    else:
                        await connection.handle_audio(item.data)

        writer_task = asyncio.create_task(writer(), name="voicebridge-serial-writer")
        reader_task = asyncio.create_task(reader(), name="voicebridge-serial-reader")
        try:
            done, _ = await asyncio.wait(
                {writer_task, reader_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                task.result()
        except ConnectionRejected:
            pass
        except ProtocolError as exc:
            with contextlib.suppress(Exception):
                await send_json({"type": "error", "code": "protocol_error", "message": str(exc)})
        finally:
            closed.set()
            for task in (writer_task, reader_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(writer_task, reader_task, return_exceptions=True)
            with contextlib.suppress(Exception):
                await connection.close()
            with contextlib.suppress(asyncio.QueueFull):
                outbound.put_nowait(None)

    async def close(self) -> None:
        self._closing = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        serial_port, self._serial = self._serial, None
        if serial_port is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(serial_port.close)
        self._state = "stopped"

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.config.transports.serial.enabled,
            "state": self._state,
            "port": self._resolved_port or self.config.transports.serial.port,
            "baudrate": self.config.transports.serial.baudrate,
            "error": self._error,
        }
