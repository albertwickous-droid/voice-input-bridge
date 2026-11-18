from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any

MAGIC = b"AUD1"
FRAME_HEADER = struct.Struct("<4sHH")
DEFAULT_MAX_CONTROL_BYTES = 64 * 1024
DEFAULT_MAX_AUDIO_FRAME_BYTES = 256 * 1024


class ProtocolError(ValueError):
    """Raised for malformed stream framing or control messages."""


@dataclass(frozen=True, slots=True)
class ControlMessage:
    value: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AudioChunk:
    data: bytes
    sequence: int | None = None


StreamItem = ControlMessage | AudioChunk


def encode_control(message: dict[str, Any]) -> bytes:
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def encode_audio_frame(data: bytes, sequence: int = 0) -> bytes:
    if len(data) > 0xFFFF:
        raise ProtocolError("an AUD1 frame payload cannot exceed 65535 bytes")
    return FRAME_HEADER.pack(MAGIC, len(data), sequence & 0xFFFF) + data


class StreamDecoder:
    """Incrementally decode newline-delimited JSON and length-prefixed AUD1 frames.

    The decoder accepts arbitrary transport chunk boundaries. In strict mode,
    binary data that is neither a valid AUD1 frame nor a JSON control message is
    rejected immediately instead of waiting forever for a newline.
    """

    def __init__(
        self,
        *,
        max_control_bytes: int = DEFAULT_MAX_CONTROL_BYTES,
        max_audio_frame_bytes: int = DEFAULT_MAX_AUDIO_FRAME_BYTES,
        strict: bool = True,
    ) -> None:
        self._buffer = bytearray()
        self._max_control_bytes = max_control_bytes
        self._max_audio_frame_bytes = max_audio_frame_bytes
        self._strict = strict

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, data: bytes | bytearray | memoryview) -> list[StreamItem]:
        if data:
            self._buffer.extend(data)
        items: list[StreamItem] = []

        while self._buffer:
            if self._strict:
                self._skip_leading_whitespace()

            if not self._buffer:
                break
            if self._buffer[:4] == MAGIC:
                if len(self._buffer) < FRAME_HEADER.size:
                    break
                _, length, sequence = FRAME_HEADER.unpack_from(self._buffer)
                if length > self._max_audio_frame_bytes:
                    raise ProtocolError(
                        f"AUD1 payload is too large: {length} > {self._max_audio_frame_bytes}"
                    )
                total = FRAME_HEADER.size + length
                if len(self._buffer) < total:
                    break
                payload = bytes(self._buffer[FRAME_HEADER.size:total])
                del self._buffer[:total]
                items.append(AudioChunk(payload, sequence=sequence))
                continue

            if self._strict:
                prefix = bytes(self._buffer[: min(4, len(self._buffer))])
                if MAGIC.startswith(prefix) and len(prefix) < len(MAGIC):
                    break
                if self._buffer[0] not in b'{["tfn-0123456789':
                    raise ProtocolError("expected an AUD1 frame or a JSON value")

            newline = self._buffer.find(b"\n")
            if newline < 0:
                if len(self._buffer) > self._max_control_bytes:
                    raise ProtocolError(
                        f"control line exceeds {self._max_control_bytes} bytes"
                    )
                break

            raw = bytes(self._buffer[:newline]).rstrip(b"\r")
            del self._buffer[: newline + 1]
            if not raw:
                continue
            if len(raw) > self._max_control_bytes:
                raise ProtocolError(
                    f"control line exceeds {self._max_control_bytes} bytes"
                )
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProtocolError(f"invalid JSON control message: {exc}") from exc
            if not isinstance(value, dict):
                raise ProtocolError("control messages must be JSON objects")
            items.append(ControlMessage(value))

        return items

    def _skip_leading_whitespace(self) -> None:
        index = 0
        while index < len(self._buffer) and self._buffer[index] in b" \t\r\n":
            index += 1
        if index:
            del self._buffer[:index]

    def reset(self) -> None:
        self._buffer.clear()
