from __future__ import annotations

import json
import struct

import pytest

from voicebridge.protocol import (
    AudioChunk,
    ControlMessage,
    ProtocolError,
    StreamDecoder,
    encode_audio_frame,
    encode_control,
)


def test_stream_decoder_handles_arbitrary_chunks() -> None:
    decoder = StreamDecoder(strict=True)
    frame = encode_audio_frame(b"\x01\x02\x03", sequence=7)
    control = encode_control({"type": "ping"})
    wire = frame + control

    assert decoder.feed(wire[:2]) == []
    items = []
    for offset in range(2, len(wire), 3):
        items.extend(decoder.feed(wire[offset : offset + 3]))

    assert items[0] == AudioChunk(b"\x01\x02\x03", sequence=7)
    assert items[1] == ControlMessage({"type": "ping"})
    assert decoder.buffered_bytes == 0


def test_stream_decoder_rejects_oversized_audio_frame() -> None:
    decoder = StreamDecoder(max_audio_frame_bytes=4, strict=True)
    header = struct.pack("<4sHH", b"AUD1", 5, 0)
    with pytest.raises(ProtocolError, match="payload is too large"):
        decoder.feed(header)


def test_stream_decoder_rejects_invalid_binary_immediately() -> None:
    decoder = StreamDecoder(strict=True)
    with pytest.raises(ProtocolError, match="expected"):
        decoder.feed(b"\x00\x01\x02\x03")


def test_stream_decoder_rejects_oversized_control_line() -> None:
    decoder = StreamDecoder(max_control_bytes=10, strict=True)
    with pytest.raises(ProtocolError, match="control line exceeds"):
        decoder.feed(b'{"type":"hello"}')


def test_stream_decoder_rejects_non_object_json() -> None:
    decoder = StreamDecoder(strict=True)
    with pytest.raises(ProtocolError, match="JSON objects"):
        decoder.feed(json.dumps(["not", "an", "object"]).encode() + b"\n")


def test_audio_encoder_respects_uint16_length() -> None:
    with pytest.raises(ProtocolError):
        encode_audio_frame(b"x" * 65_536)
