"""Face embedding similarity and confidence-band labelling.

Cosine similarity over ArcFace embeddings. The band wording is deliberately
hedged — "potential match", never "confirmed identity".
"""
from __future__ import annotations

import math

from app.database.entities import ConfidenceBand

# Thresholds tuned for buffalo_l / ArcFace normed embeddings (cosine in [-1, 1]).
POTENTIAL_MATCH = 0.50
STRONG = 0.40
POSSIBLE = 0.28

# At/above this cosine, two faces are treated as the SAME face (near-identical
# crop) for deduplication — high enough not to merge genuinely different photos.
DEDUP_THRESHOLD = 0.92


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def band_for_similarity(score: float) -> ConfidenceBand | None:
    """Return a hedged band, or None when below the 'possible' floor."""
    if score >= POTENTIAL_MATCH:
        return ConfidenceBand.POTENTIAL_MATCH
    if score >= STRONG:
        return ConfidenceBand.STRONG
    if score >= POSSIBLE:
        return ConfidenceBand.POSSIBLE
    return None


def is_match(score: float) -> bool:
    return score >= POSSIBLE
