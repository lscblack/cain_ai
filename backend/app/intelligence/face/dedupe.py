"""Near-duplicate face removal.

Groups faces by source host and drops embeddings that are near-identical to one
already kept (highest quality wins). Used both by the manual endpoint and an
automatic background pass so the index stays deduplicated without operator action.

The heavy O(n^2)-per-host comparison runs off the event loop (worker thread) so it
never blocks interactive API traffic or the worker's other background loops.
"""
from __future__ import annotations

from urllib.parse import urlsplit

import anyio
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.models.face import Face
from app.intelligence.face.crops import crop_path
from app.intelligence.face.similarity import DEDUP_THRESHOLD
from app.intelligence.face.vector_index import max_similarity

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
    Returns the ids of near-identical faces to drop (keeping the first/best per host)."""
    kept: dict[str, list[list[float]]] = {}
    remove_ids: list = []
    for fid, host, emb in rows:
        if not emb:
            continue
        bucket = kept.setdefault(host, [])
        if max_similarity(list(emb), bucket) >= DEDUP_THRESHOLD:
            remove_ids.append(fid)
        else:
            bucket.append(list(emb))
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
