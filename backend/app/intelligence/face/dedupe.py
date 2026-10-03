"""Near-duplicate face removal.

Groups faces by source host and drops embeddings that are near-identical to one
already kept (highest quality wins). Used both by the manual endpoint and an
automatic background pass so the index stays deduplicated without operator action.

The heavy O(n^2)-per-host comparison runs off the event loop (worker thread) so it
never blocks interactive API traffic or the worker's other background loops.
"""
from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlsplit

import anyio
import numpy as np
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.models.face import Face
from app.intelligence.face.crops import crop_path
from app.intelligence.face.similarity import DEDUP_THRESHOLD

logger = get_logger("kai.face.dedupe")


def _host(url: str | None) -> str:
    if not url:
        return "none"
    try:
        return urlsplit(url).hostname or url
    except Exception:
        return url


def _find_duplicates(rows: list[tuple]) -> list:
    """Pure-CPU pass: rows are (id, host, embedding) ordered best-quality-first.
    Returns ids of near-identical faces to drop (keeping the best per host).

    Per host we keep a single growing matrix of unit-normalised embeddings and do
    one vectorised dot product per face — O(k) per face instead of rebuilding the
    whole bucket array every comparison (which made large hosts O(k^2) allocations).
    """
    by_host: dict[str, list[tuple]] = defaultdict(list)
    for fid, host, emb in rows:
        if emb:
            by_host[host].append((fid, emb))

    remove_ids: list = []
    for host, items in by_host.items():
        dim = len(items[0][1])
        kept = np.empty((len(items), dim), dtype=np.float32)  # preallocated once
        n = 0
        for fid, emb in items:
            v = np.asarray(emb, dtype=np.float32)
            if v.shape[0] != dim:
                continue
            norm = np.linalg.norm(v)
            v = v / (norm or 1e-12)
            if n and float((kept[:n] @ v).max()) >= DEDUP_THRESHOLD:
                remove_ids.append(fid)
                continue
            kept[n] = v
            n += 1
    return remove_ids


async def run_dedupe(session: AsyncSession) -> dict:
    """Remove near-identical faces within the same source (keeps highest quality).

    Returns {removed, remaining}. Safe to call repeatedly; a clean index removes 0.
    """
    faces = (await session.execute(select(Face).order_by(desc(Face.quality)))).scalars().all()
    total = len(faces)
    rows = [(f.id, _host(f.source_url), list(f.embedding) if f.embedding else None) for f in faces]

    # Heavy comparison off the event loop so nothing else stalls.
    remove_ids = await anyio.to_thread.run_sync(_find_duplicates, rows)

    if remove_ids:
        await session.execute(delete(Face).where(Face.id.in_(remove_ids)))
        await session.commit()
        for fid in remove_ids:
            try:
                p = crop_path(str(fid))
                if p.exists():
                    p.unlink()
            except Exception:
                pass
    return {"removed": len(remove_ids), "remaining": total - len(remove_ids)}
