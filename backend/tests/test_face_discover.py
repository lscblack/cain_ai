"""Mode A discovery pipeline — offline via fake provider + fixture faces."""
import pathlib

import pytest

from app.intelligence.face.discover import discover_faces
from app.intelligence.face.service import get_face_engine

FIX = pathlib.Path(__file__).parent / "fixtures"
engine = get_face_engine()
requires_engine = pytest.mark.skipif(not engine.available(), reason="face engine unavailable")


@requires_engine
async def test_discover_finds_matching_candidate():
    query = (FIX / "face1.jpg").read_bytes()
    same = (FIX / "face1.jpg").read_bytes()
    other = (FIX / "face2.jpg").read_bytes()

    store = {
        "https://cdn.example/same.jpg": same,
        "https://cdn.example/other.jpg": other,
        "https://cdn.example/dupe.jpg": same,  # duplicate bytes
    }

    async def fetch(url):
        return store.get(url)

    async def safe(url):
        return "127.0.0.1" not in url and "localhost" not in url

    candidates = [
        {"provider": "fake", "image_url": "https://cdn.example/same.jpg", "source_url": "https://news/1"},
        {"provider": "fake", "image_url": "https://cdn.example/other.jpg", "source_url": "https://news/2"},
        {"provider": "fake", "image_url": "https://cdn.example/dupe.jpg", "source_url": "https://news/3"},
        {"provider": "fake", "image_url": "http://127.0.0.1/evil.jpg", "source_url": "https://news/4"},  # SSRF
    ]

    res = await discover_faces(query, candidates, engine=engine, image_fetch=fetch, safe_check=safe)
    assert res.query_detected is True
    assert res.duplicates_skipped == 1          # the dupe
    # the matching candidate (same person) should be a strong match
    assert any(m["similarity"] > 0.9 for m in res.matches)
    # the different person should not be a strong match
    assert all(not (m["source_url"] == "https://news/2" and m["similarity"] > 0.5) for m in res.matches)
    assert "fake" in res.providers_used


@requires_engine
async def test_discover_no_query_face():
    # a tiny non-face image
    blank = (FIX / "face1.jpg").read_bytes()[:50]  # truncated -> likely no face / undecodable

    async def fetch(url):
        return None

    res = await discover_faces(blank, [], engine=engine, image_fetch=fetch)
    assert res.query_detected is False
