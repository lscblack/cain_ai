"""Global face discovery (Mode A) — verification pipeline.

Given a query face and candidate image references from external reverse-image
providers, KAI downloads each permitted candidate, detects/embeds faces locally,
compares to the query, deduplicates, and ranks. This local verification is the
real intelligence; the external providers only supply candidate URLs and are
key-gated (UNAVAILABLE without credentials — never fabricated).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.core.net import UnsafeUrlError, validate_public_url
from app.intelligence.face.dedup import sha256_bytes
from app.intelligence.face.engine import FaceEngine
from app.intelligence.face.similarity import POSSIBLE, band_for_similarity, cosine_similarity

# image_fetch(url) -> bytes | None
ImageFetch = Callable[[str], Awaitable[bytes | None]]


@dataclass
class DiscoveryResult:
    query_detected: bool
    matches: list[dict] = field(default_factory=list)
    candidates_seen: int = 0
    candidates_downloaded: int = 0
    duplicates_skipped: int = 0
    providers_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query_detected": self.query_detected,
            "matches": self.matches,
            "candidates_seen": self.candidates_seen,
            "candidates_downloaded": self.candidates_downloaded,
            "duplicates_skipped": self.duplicates_skipped,
            "providers_used": self.providers_used,
        }


async def _safe(url: str) -> bool:
    try:
        validate_public_url(url)
        return True
    except UnsafeUrlError:
        return False


async def discover_faces(
    query_bytes: bytes,
    candidates: list[dict],
    *,
    engine: FaceEngine,
    image_fetch: ImageFetch,
    floor: float = POSSIBLE,
    max_candidates: int = 60,
    safe_check: Callable[[str], Awaitable[bool]] | None = None,
) -> DiscoveryResult:
    """candidates: list of {provider, image_url, source_url, title}."""
    safe = safe_check or _safe
    try:
        q_faces = engine.detect_and_embed(query_bytes)
    except Exception:
        q_faces = []
    if not q_faces:
        return DiscoveryResult(query_detected=False)
    query = q_faces[0].embedding

    result = DiscoveryResult(query_detected=True)
    seen_hashes: set[str] = set()
    providers: set[str] = set()

    for cand in candidates[:max_candidates]:
        result.candidates_seen += 1
        if cand.get("provider"):
            providers.add(cand["provider"])
        img_url = cand.get("image_url")
        if not img_url or not await safe(img_url):
            continue
        try:
            data = await image_fetch(img_url)
        except Exception:
            data = None
        if not data:
            continue
        h = sha256_bytes(data)
        if h in seen_hashes:
            result.duplicates_skipped += 1
            continue
        seen_hashes.add(h)
        result.candidates_downloaded += 1

        try:
            faces = engine.detect_and_embed(data)
        except Exception:
            faces = []
        if not faces:
            continue
        # best similarity among faces found in the candidate image
        best = max((cosine_similarity(query, f.embedding) for f in faces), default=0.0)
        if best < floor:
            continue
        band = band_for_similarity(best)
        result.matches.append(
            {
                "provider": cand.get("provider"),
                "source_url": cand.get("source_url"),
                "image_url": img_url,
                "title": cand.get("title"),
                "image_hash": h,
                "similarity": round(best, 4),
                "similarity_pct": round(best * 100, 1),
                "band": band.value if band else "no_match",
            }
        )

    result.matches.sort(key=lambda m: m["similarity"], reverse=True)
    result.providers_used = sorted(providers)
    return result
