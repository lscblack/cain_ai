"""In-memory face index for fast 1:N search over the WHOLE corpus.

Embeddings live in Postgres as JSONB; decoding ~230k of them takes ~50 s, far too
slow per search. This cache loads them once (as text → numpy, L2-normalised,
float16 ≈ 1 KB/face) and afterwards only pulls faces created since the last
refresh. A drop in the row count (dedupe / deletes) triggers a full reload.

Search is a chunked matrix multiply: ~0.1 s for 230k faces.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

import numpy as np
from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.face import Face

log = logging.getLogger(__name__)

_BATCH = 20000
_CHUNK = 50000  # rows per matmul chunk (float16 → float32 upcast per chunk)


def _parse(text: str | None) -> np.ndarray | None:
    if not text or len(text) < 3:
        return None
    v = np.fromstring(text.strip()[1:-1], sep=",", dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else None


class _DimIndex:
    """All embeddings of one dimensionality."""

    def __init__(self) -> None:
        self.ids: list[str] = []
        self.parts: list[np.ndarray] = []
        self.mat: np.ndarray | None = None

    def add(self, ids: list[str], vecs: list[np.ndarray]) -> None:
        if ids:
            self.ids.extend(ids)
            self.parts.append(np.vstack(vecs).astype(np.float16))
            self.mat = None

    def matrix(self) -> np.ndarray:
        if self.mat is None:
            self.mat = np.vstack(self.parts) if len(self.parts) > 1 else self.parts[0]
            self.parts = [self.mat]
        return self.mat


class FaceIndexCache:
    def __init__(self) -> None:
        self._dims: dict[int, _DimIndex] = {}
        self._known: set[str] = set()
        self._count = 0
        self._since: datetime | None = None
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        return len(self._known)

    async def _load(self, session: AsyncSession, since: datetime | None) -> int:
        added = 0
        last_ts, last_id = since, None
        while True:
            stmt = (select(Face.id, Face.created_at, cast(Face.embedding, Text))
                    .order_by(Face.created_at, Face.id).limit(_BATCH))
            if last_ts is not None:
                stmt = stmt.where(Face.created_at >= last_ts) if last_id is None else stmt.where(
                    (Face.created_at > last_ts) | ((Face.created_at == last_ts) & (Face.id > last_id)))
            rows = (await session.execute(stmt)).all()
            if not rows:
                return added
            by_dim: dict[int, tuple[list[str], list[np.ndarray]]] = {}
            for fid, _ts, text in rows:
                sid = str(fid)
                if sid in self._known:
                    continue
                v = _parse(text)
                if v is None:
                    continue
                ids, vecs = by_dim.setdefault(v.shape[0], ([], []))
                ids.append(sid)
                vecs.append(v)
                self._known.add(sid)
            for dim, (ids, vecs) in by_dim.items():
                self._dims.setdefault(dim, _DimIndex()).add(ids, vecs)
                added += len(ids)
            last_ts, last_id = rows[-1][1], rows[-1][0]
            self._since = last_ts

    async def refresh(self, session: AsyncSession) -> None:
        """Bring the cache up to date with the table (incremental when possible)."""
        async with self._lock:
            count = int((await session.execute(select(func.count()).select_from(Face))).scalar_one())
            t = time.time()
            if count < self._count or not self._known:
                self._dims, self._known, self._since = {}, set(), None
                added = await self._load(session, None)
                log.info("face index cache: full load of %d faces in %.1fs", added, time.time() - t)
            elif count > self._count:
                added = await self._load(session, self._since)
                if added:
                    log.info("face index cache: +%d new faces in %.1fs", added, time.time() - t)
            self._count = count

    async def search(
        self, session: AsyncSession, queries: list[list[float]], *, floor: float,
    ) -> dict[str, float]:
        """``{face_id: best cosine ≥ floor}`` across every indexed face."""
        await self.refresh(session)
        best: dict[str, float] = {}
        for q in queries:
            qv = np.asarray(q, dtype=np.float32)
            n = float(np.linalg.norm(qv))
            idx = self._dims.get(qv.shape[0])
            if n == 0 or idx is None or not idx.ids:
                continue
            qv /= n
            mat = idx.matrix()
            for start in range(0, mat.shape[0], _CHUNK):
                scores = mat[start:start + _CHUNK].astype(np.float32) @ qv
                for j in np.nonzero(scores >= floor)[0]:
                    fid = idx.ids[start + int(j)]
                    sc = float(scores[j])
                    if sc > best.get(fid, 0.0):
                        best[fid] = sc
        return best


_cache = FaceIndexCache()


def get_index_cache() -> FaceIndexCache:
    return _cache
