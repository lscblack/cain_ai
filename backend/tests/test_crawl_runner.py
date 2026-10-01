"""Crawler pipeline tests — fully offline via injected fetcher + fake engine."""
from __future__ import annotations

from sqlalchemy import func, select

from app.crawlers.runner import Fetched, crawl_source
from app.database.models.face import Face
from app.database.models.source import Image, Page, Source
from app.intelligence.face.engine import DetectedFace, FaceEngine


import hashlib


def _orthoish(image_bytes: bytes) -> list[float]:
    """A distinct vector per unique image bytes (so different images != same face)."""
    h = hashlib.sha256(image_bytes).digest()
    return [b / 255.0 for b in h[:16]]


class FakeEngine(FaceEngine):
    model_name = "fake"
    model_version = "1"
    embedding_dim = 16

    def __init__(self, faces_per_image=1, constant: bool = False):
        self.faces_per_image = faces_per_image
        self.constant = constant

    def available(self) -> bool:
        return True

    def detect_and_embed(self, image_bytes: bytes):
        emb = [1.0] + [0.0] * 15 if self.constant else _orthoish(image_bytes)
        return [
            DetectedFace(bbox=[0, 0, 10, 10], det_score=0.9, embedding=list(emb), quality=0.8)
            for _ in range(self.faces_per_image)
        ]


PAGE_HTML = """
<html><body>
  <img src="/img/a.jpg">
  <img src="/img/b.png">
  <a href="/news/story">more</a>
</body></html>
""".encode()

STORY_HTML = b"<html><body><img src='/img/c.jpg'></body></html>"


def make_fetch(image_bytes=None):
    async def fetch(url: str) -> Fetched:
        if url.endswith((".jpg", ".png")):
            # distinct bytes per URL unless a fixed payload is forced (dedup test)
            body = image_bytes if image_bytes is not None else (b"IMG:" + url.encode())
            return Fetched(status=200, content_type="image/jpeg", body=body)
        if url.rstrip("/").endswith("/news/story"):
            return Fetched(status=200, content_type="text/html", body=STORY_HTML)
        if "example.com" in url:
            return Fetched(status=200, content_type="text/html", body=PAGE_HTML)
        return Fetched(status=404)

    return fetch


async def _always_safe(url: str) -> bool:
    return True


def _source() -> Source:
    return Source(
        name="Test", base_url="https://example.com/", domain="example.com",
        allowed_paths=[], excluded_paths=[], max_depth=1, max_pages=10,
    )


async def test_crawl_indexes_pages_images_faces(db_session):
    src = _source()
    db_session.add(src)
    await db_session.commit()

    stats = await crawl_source(
        db_session, src, fetch=make_fetch(), engine=FakeEngine(), safe_check=_always_safe
    )
    await db_session.commit()

    assert stats.pages_processed >= 1
    assert stats.images_indexed >= 2
    assert stats.faces_indexed >= 2

    pages = (await db_session.execute(select(func.count()).select_from(Page))).scalar_one()
    faces = (await db_session.execute(select(func.count()).select_from(Face))).scalar_one()
    assert pages >= 1 and faces >= 2


async def test_crawl_dedupes_identical_images(db_session):
    src = _source()
    db_session.add(src)
    await db_session.commit()
    # same image bytes everywhere -> only first indexed, rest duplicates
    stats = await crawl_source(
        db_session, src, fetch=make_fetch(b"SAMEBYTES"), engine=FakeEngine(), safe_check=_always_safe
    )
    await db_session.commit()
    images = (await db_session.execute(select(func.count()).select_from(Image))).scalar_one()
    assert images == 1
    assert stats.images_duplicate >= 1


async def test_crawl_incremental_skip_unchanged(db_session):
    src = _source()
    db_session.add(src)
    await db_session.commit()
    fetch = make_fetch()
    await crawl_source(db_session, src, fetch=fetch, engine=FakeEngine(), safe_check=_always_safe)
    await db_session.commit()
    # second crawl: content unchanged -> pages skipped
    stats2 = await crawl_source(db_session, src, fetch=fetch, engine=FakeEngine(), safe_check=_always_safe)
    await db_session.commit()
    assert stats2.pages_skipped >= 1
    assert stats2.pages_processed == 0


async def test_crawl_respects_excluded_paths(db_session):
    src = Source(
        name="T", base_url="https://example.com/", domain="example.com",
        allowed_paths=[], excluded_paths=["/news"], max_depth=1, max_pages=10,
    )
    db_session.add(src)
    await db_session.commit()
    await crawl_source(db_session, src, fetch=make_fetch(), engine=FakeEngine(), safe_check=_always_safe)
    await db_session.commit()
    urls = [p.url for p in (await db_session.execute(select(Page))).scalars().all()]
    assert all("/news/story" not in u for u in urls)


async def test_crawl_dedupes_same_face_across_images(db_session):
    """Different image bytes but identical face embedding -> only one face kept."""
    src = _source()
    db_session.add(src)
    await db_session.commit()
    # constant=True => every detected face has the same embedding
    stats = await crawl_source(
        db_session, src, fetch=make_fetch(), engine=FakeEngine(constant=True), safe_check=_always_safe
    )
    await db_session.commit()
    faces = (await db_session.execute(select(func.count()).select_from(Face))).scalar_one()
    assert faces == 1                      # all near-identical faces collapsed to one
    assert stats.faces_duplicate >= 1
