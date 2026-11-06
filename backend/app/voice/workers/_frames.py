"""Length-prefixed frames shared by the backend and the worker processes.

Standard library only: this file is executed by the isolated model environments too.

    4 bytes  JSON header length (big endian)
    4 bytes  binary payload length (big endian)
    header   UTF-8 JSON object
    payload  raw bytes (PCM audio, or empty)
"""
from __future__ import annotations

import json
import struct

_PREFIX = struct.Struct(">II")
PREFIX_SIZE = _PREFIX.size
MAX_HEADER = 4 * 1024 * 1024
MAX_PAYLOAD = 64 * 1024 * 1024


class FrameError(Exception):
    """The peer sent something that is not a valid frame."""


def encode(header: dict, payload: bytes = b"") -> bytes:
    raw = json.dumps(header, separators=(",", ":")).encode()
    return _PREFIX.pack(len(raw), len(payload)) + raw + payload


def parse_prefix(prefix: bytes) -> tuple[int, int]:
    header_len, payload_len = _PREFIX.unpack(prefix)
    if header_len > MAX_HEADER or payload_len > MAX_PAYLOAD:
        raise FrameError(f"frame too large: header={header_len} payload={payload_len}")
    return header_len, payload_len


def read_blocking(stream) -> tuple[dict, bytes] | None:
    """Read one frame from a binary file object; None on a clean end of stream."""
    prefix = stream.read(PREFIX_SIZE)
    if not prefix:
        return None
    if len(prefix) < PREFIX_SIZE:
        raise FrameError("truncated prefix")
    header_len, payload_len = parse_prefix(prefix)
    raw = stream.read(header_len)
    payload = stream.read(payload_len) if payload_len else b""
    if len(raw) < header_len or len(payload) < payload_len:
        raise FrameError("truncated frame")
    return json.loads(raw), payload
