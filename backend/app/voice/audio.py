"""AudioProcessingService (backend side): validates uploads before any model sees them.

Decoding and analysis happen in the isolated worker; this only needs the standard library
so a hostile file is rejected without being parsed by anything elaborate.
"""
from __future__ import annotations

from pathlib import Path

ALLOWED_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".oga", ".opus", ".webm", ".m4a", ".mp4", ".aac"}


class AudioValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def sniff_audio_container(head: bytes) -> str | None:
    """Identify a container from its magic bytes; None when it is not an accepted format."""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if len(head) > 1 and head[0] == 0xFF and head[1] & 0xF6 == 0xF0:
        return "aac"  # ADTS: sync bits with a zero layer field
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0 and head[1] & 0x06):
        return "mp3"
    if head[4:8] == b"ftyp":
        return "m4a"
    return None


def validate_upload(filename: str | None, head: bytes) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix and suffix not in ALLOWED_SUFFIXES:
        raise AudioValidationError("unsupported_audio_format")
    container = sniff_audio_container(head)
    if container is None:
        raise AudioValidationError("unsupported_audio_format")
    return container
