"""Image hashing & deduplication.

- SHA-256 for exact file duplicates.
- Average perceptual hash (aHash) for near-duplicates.
These are distinct concepts from "same face" / "same person" (handled by
embeddings) and must never be conflated.
"""
from __future__ import annotations

import hashlib


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def average_hash(image_bytes: bytes, hash_size: int = 8) -> str | None:
    """64-bit average hash as a 16-char hex string, or None if undecodable."""
    try:
        import io

        from PIL import Image as PILImage

        img = PILImage.open(io.BytesIO(image_bytes)).convert("L").resize(
            (hash_size, hash_size)
        )
        pixels = list(img.getdata())
    except Exception:
        return None
    avg = sum(pixels) / len(pixels)
    bits = 0
    for px in pixels:
        bits = (bits << 1) | (1 if px >= avg else 0)
    width = hash_size * hash_size // 4
    return f"{bits:0{width}x}"


def hamming_distance(hex_a: str, hex_b: str) -> int:
    if not hex_a or not hex_b or len(hex_a) != len(hex_b):
        return 10**9
    return bin(int(hex_a, 16) ^ int(hex_b, 16)).count("1")


def is_near_duplicate(hex_a: str, hex_b: str, *, threshold: int = 5) -> bool:
    return hamming_distance(hex_a, hex_b) <= threshold
