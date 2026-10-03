"""Live search / browse over crawled non-image data (emails, phones, usernames).

Substring search across the JSONB contact arrays on crawled pages, so an operator
can find a partial handle/number/email as they type — not just exact matches.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.database.models.user import User
from app.database.session import get_session

router = APIRouter(prefix="/contacts", tags=["contacts"])

_KIND_COL = {"email": "emails", "phone": "phones", "username": "usernames"}


def _query_for(col: str) -> str:
    # Distinct contact values of one kind, with how many pages mention them + a sample.
    return f"""
        SELECT v.val AS value, '{col}' AS kind,
               count(DISTINCT p.url) AS pages,
               (array_agg(p.url ORDER BY p.last_crawled_at DESC NULLS LAST))[1] AS sample_url,
               (array_agg(p.title ORDER BY p.last_crawled_at DESC NULLS LAST))[1] AS sample_title
        FROM pages p, jsonb_array_elements_text(p.{col}) AS v(val)
        WHERE (:q = '' OR v.val ILIKE :like)
        GROUP BY v.val
    """


@router.get("/search")
async def search_contacts(
    q: str = Query(default="", max_length=120),
    kind: str = Query(default="all"),
    limit: int = Query(default=60, ge=1, le=200),
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Live substring search over crawled emails / phones / usernames.

    Empty q -> browse the most-common contacts. kind: all|email|phone|username.
    """
    cols = [_KIND_COL[kind]] if kind in _KIND_COL else list(_KIND_COL.values())
    union = "\nUNION ALL\n".join(_query_for(c) for c in cols)
    sql = text(
        f"SELECT value, kind, pages, sample_url, sample_title FROM (\n{union}\n) t "
        "ORDER BY pages DESC, value ASC LIMIT :limit"
    )
    like = f"%{q.strip()}%"
    rows = (await session.execute(sql, {"q": q.strip(), "like": like, "limit": limit})).mappings().all()
    return {
        "query": q,
        "kind": kind,
        "count": len(rows),
        "results": [dict(r) for r in rows],
    }


@router.get("/stats")
async def contacts_stats(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """How much non-image data has been harvested so far."""
    sql = text(
        """
        SELECT
          (SELECT count(*) FROM pages) AS pages,
          (SELECT count(DISTINCT e) FROM pages, jsonb_array_elements_text(emails) e) AS emails,
          (SELECT count(DISTINCT p) FROM pages, jsonb_array_elements_text(phones) p) AS phones,
          (SELECT count(DISTINCT u) FROM pages, jsonb_array_elements_text(usernames) u) AS usernames
        """
    )
    row = (await session.execute(sql)).mappings().one()
    return dict(row)
