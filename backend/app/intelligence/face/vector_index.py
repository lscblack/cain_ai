"""Vectorized in-memory cosine search over stored face embeddings.

A NumPy matmul over the whole corpus — materially faster than a per-row Python
loop. For the spec's 1M–10M target, swap this for pgvector/Qdrant ANN (see
docs/KAI_REPAIR_PLAN.md P2.1); the call site stays the same.
"""
from __future__ import annotations

import numpy as np


def rank_by_cosine(
    query: list[float],
    corpus: list[tuple[str, list[float]]],
    *,
    floor: float,
) -> list[tuple[str, float]]:
    """Return (id, score) pairs with score >= floor, highest first.

    corpus: list of (id, embedding). Embeddings may be any length; mismatched or
    empty ones are skipped.
    """
    if not query or not corpus:
        return []
    dim = len(query)
    ids: list[str] = []
    rows: list[list[float]] = []
    for cid, emb in corpus:
        if emb and len(emb) == dim:
            ids.append(cid)
            rows.append(emb)
    if not rows:
        return []

    q = np.asarray(query, dtype=np.float32)
    m = np.asarray(rows, dtype=np.float32)

    qn = np.linalg.norm(q)
    mn = np.linalg.norm(m, axis=1)
    denom = mn * qn
    denom[denom == 0.0] = 1e-12
    scores = (m @ q) / denom

    out = [(ids[i], float(scores[i])) for i in range(len(ids)) if scores[i] >= floor]
    out.sort(key=lambda t: t[1], reverse=True)
    return out
