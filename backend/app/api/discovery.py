"""Source Discovery Engine API.

Operators launch a discovery run (discover -> qualify -> score -> approve -> crawl)
and poll its live progress. Also exposes the self-learning term queue so searched
terms with little/no local data get auto-discovered next time.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.crawlers.queue import enqueue_discovery
from app.database.models.user import User
from app.database.session import get_session
from app.discovery import learning
from app.discovery.dossier import gather_dossier
from app.discovery.engine import INVESTIGATIONS_KEY, _run_key, mark_queued, new_run_id
from app.discovery.search import search_available

logger = get_logger("kai.api.discovery")
router = APIRouter(prefix="/discovery", tags=["discovery"])


class DiscoveryRunIn(BaseModel):
    countries: list[str] = Field(default_factory=list, max_length=30)
    country: str | None = Field(default=None, max_length=80)  # back-compat (single)
    categories: list[str] = Field(default_factory=lambda: ["people", "phone", "images"])
    targets: list[str] = Field(default_factory=lambda: ["phone", "username", "images"])
    min_score: int = Field(default=60, ge=0, le=100)
    max_domains: int = Field(default=200, ge=1, le=500)
    auto_crawl: bool = False

    def resolved_countries(self) -> list[str]:
        out = [c.strip() for c in self.countries if c and c.strip()]
        if not out and self.country and self.country.strip():
            out = [self.country.strip()]
        return out or ["rwanda"]


class DiscoveryRunStarted(BaseModel):
    id: str
    available: bool


@router.get("/status")
async def discovery_status(operator: User = Depends(get_current_operator)) -> dict:
    return {"available": search_available()}


@router.post("/run", response_model=DiscoveryRunStarted, status_code=status.HTTP_202_ACCEPTED)
async def start_discovery(
    body: DiscoveryRunIn,
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> DiscoveryRunStarted:
    if not search_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discovery search unavailable: set SERPAPI_API_KEY.",
        )
    run_id = new_run_id()
    params = {
        "run_id": run_id,
        "countries": body.resolved_countries(),
        "categories": body.categories,
        "targets": body.targets,
        "min_score": body.min_score,
        "max_domains": body.max_domains,
        "auto_crawl": body.auto_crawl,
    }
    # Run in the background worker (de-prioritised process) so a discovery run never
    # competes with interactive API traffic. The UI polls progress from Redis.
    await mark_queued(redis, run_id, params)
    await enqueue_discovery(redis, params)
    logger.info("discovery run %s queued by %s", run_id, operator.email)
    return DiscoveryRunStarted(id=run_id, available=True)


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> dict:
    raw = await redis.get(_run_key(run_id))
    if raw is None:
        raise HTTPException(status_code=404, detail="Run not found or expired.")
    return json.loads(raw)


@router.get("/terms")
async def list_terms(
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> dict:
    return {"terms": await learning.list_terms(redis)}


@router.delete("/terms", status_code=status.HTTP_204_NO_CONTENT)
async def clear_terms(
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> None:
    await learning.clear_terms(redis)


# ── Name investigations (batch) ──────────────────────────────────────────────

class InvestigateIn(BaseModel):
    names: list[str] = Field(min_length=1, max_length=500)
    queries: list[str] = Field(default_factory=list, max_length=60)  # operator query tips
    auto_crawl: bool = True


@router.post("/investigate", response_model=DiscoveryRunStarted, status_code=status.HTTP_202_ACCEPTED)
async def investigate_names(
    body: InvestigateIn,
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> DiscoveryRunStarted:
    """Upload a list of names → background investigation that discovers + crawls
    sources and surfaces the images/phones/emails/usernames that might belong to them."""
    names = [n.strip() for n in body.names if n and n.strip()][:500]
    if not names:
        raise HTTPException(status_code=422, detail="No valid names provided.")
    run_id = new_run_id()
    await mark_queued(redis, run_id, {"targets": names})
    # reflect investigation shape in the queued state
    from app.discovery.onion import onion_available

    raw = await redis.get(_run_key(run_id))
    state = json.loads(raw) if raw else {}
    state.update({"kind": "investigation", "names": names, "status": "queued",
                  "onion_enabled": onion_available(), "onion_sources": 0})
    await redis.set(_run_key(run_id), json.dumps(state), ex=60 * 60 * 24)
    await redis.lpush(INVESTIGATIONS_KEY, run_id)
    await redis.ltrim(INVESTIGATIONS_KEY, 0, 199)
    tips = [q.strip() for q in body.queries if q and q.strip()][:60]
    await enqueue_discovery(redis, {"kind": "names", "run_id": run_id, "names": names,
                                    "queries": tips, "auto_crawl": body.auto_crawl})
    logger.info("name investigation %s queued by %s (%d names)", run_id, operator.email, len(names))
    return DiscoveryRunStarted(id=run_id, available=search_available())


class AskIn(BaseModel):
    question: str
    auto_crawl: bool = True


# Filler/question words stripped before resolving the subject of a question.
_QUESTION_FILLER = {
    "i", "want", "to", "know", "about", "who", "is", "are", "was", "were", "the",
    "of", "tell", "me", "what", "whats", "give", "info", "information", "on",
    "please", "can", "could", "you", "find", "show", "details", "detail", "a",
    "an", "for", "more", "everything", "regarding", "research", "investigate",
    "look", "up", "search", "get", "need", "would", "like", "there", "any", "all",
    "data", "do", "does", "his", "her", "their", "this", "that", "and", "with",
    "person", "named", "name", "call", "called", "profile", "background",
}

_SUBJECT_QUERIES = (
    "", " biography", " age date of birth", " wife husband children family",
    " photos images",
)


def _clean_question(q: str) -> str:
    """Strip filler/question words, keeping the meaningful subject terms."""
    import re

    words = re.findall(r"[A-Za-z0-9.&'\-]+", q.lower())
    kept = [w for w in words if w not in _QUESTION_FILLER and len(w) > 1]
    return " ".join(kept).strip()


def _subject_queries(subject: str) -> list[str]:
    return [f"{subject}{suffix}" for suffix in _SUBJECT_QUERIES]


async def _resolve_subject(question: str) -> tuple[str, list[str]]:
    """Turn a natural-language question into a subject + web queries, covering
    bio, age, family and photos. Public-OSINT only.

    Keyless by default: strips filler words then resolves a canonical subject via
    Wikipedia's free opensearch API (e.g. "i want to know about president paul
    kagame" -> "Paul Kagame"). An AI provider, if actually reachable, may refine
    it — but resolution never DEPENDS on one (the provider here 402s)."""
    from app.discovery.search import wikipedia_article

    q = question.strip()
    cleaned = _clean_question(q) or q

    # Aspect words describe what the operator wants ABOUT the subject, not the
    # subject itself — drop them when resolving the canonical name.
    aspects = {
        "family", "wife", "husband", "children", "child", "spouse", "parents",
        "father", "mother", "son", "daughter", "age", "biography", "bio",
        "photos", "photo", "images", "image", "pictures", "picture", "date",
        "birth", "born", "death", "died", "net", "worth", "education", "career",
        "history", "life", "story", "details",
    }
    core = " ".join(w for w in cleaned.split() if w not in aspects).strip()

    # 1) Keyless canonical resolution via Wikipedia (always available). Try the
    #    core phrase, then progressively shorter prefixes, first hit wins.
    tokens = (core or cleaned).split()
    candidates = [core, cleaned] + [" ".join(tokens[:n]) for n in (4, 3, 2)]
    subject = core or cleaned
    for cand in dict.fromkeys([c for c in candidates if c]):
        try:
            art = await wikipedia_article(cand)
        except Exception:
            art = None
        if art:
            subject = art[1]  # canonical article title, e.g. "Paul Kagame"
            break
    queries = _subject_queries(subject)

    # 2) Optional AI refinement — only if the provider is truly working.
    try:
        from app.ai.router import AIMessage, get_ai_provider

        provider = get_ai_provider()
        if provider is not None and provider.available():
            system = (
                "Extract the primary PERSON a question is about. Return STRICT JSON only: "
                '{"subject": "<full name or best guess>", "queries": ["<web search query>", ...]}. '
                "Include queries covering biography, age/date of birth, family (spouse, children, "
                "parents) and photos. Public OSINT only. If no specific person is implied, set "
                "subject to the key phrase."
            )
            out = await provider.chat(
                [AIMessage(role="system", content=system), AIMessage(role="user", content=q)]
            )
            data = json.loads(out[out.find("{"): out.rfind("}") + 1])
            ai_subject = (str(data.get("subject") or "")).strip()
            ai_queries = [str(x).strip() for x in (data.get("queries") or []) if str(x).strip()][:20]
            if ai_subject:
                subject = ai_subject
                queries = ai_queries or _subject_queries(ai_subject)
    except Exception:
        pass  # AI unavailable/unpaid — keep the keyless result

    return subject, queries


@router.post("/ask", response_model=DiscoveryRunStarted, status_code=status.HTTP_202_ACCEPTED)
async def ask(
    body: AskIn,
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> DiscoveryRunStarted:
    """Natural-language investigation: 'who is the president of Rwanda' → resolve
    the subject, then discover + crawl public sources for their bio, age, family
    and images. Potential leads from public data, never confirmed identity."""
    if not body.question.strip():
        raise HTTPException(status_code=422, detail="Empty question.")
    subject, queries = await _resolve_subject(body.question)
    names = [subject][:1]
    run_id = new_run_id()
    await mark_queued(redis, run_id, {"targets": names})
    from app.discovery.onion import onion_available

    raw = await redis.get(_run_key(run_id))
    state = json.loads(raw) if raw else {}
    state.update({"kind": "investigation", "names": names, "status": "queued",
                  "question": body.question.strip(),
                  "onion_enabled": onion_available(), "onion_sources": 0})
    await redis.set(_run_key(run_id), json.dumps(state), ex=60 * 60 * 24)
    await redis.lpush(INVESTIGATIONS_KEY, run_id)
    await redis.ltrim(INVESTIGATIONS_KEY, 0, 199)
    await enqueue_discovery(redis, {"kind": "names", "run_id": run_id, "names": names,
                                    "queries": queries[:60], "auto_crawl": body.auto_crawl})
    logger.info("ask investigation %s queued by %s: %r -> %r",
                run_id, operator.email, body.question[:80], subject)
    return DiscoveryRunStarted(id=run_id, available=search_available())


@router.get("/investigations")
async def list_investigations(
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> dict:
    try:
        ids = await redis.lrange(INVESTIGATIONS_KEY, 0, 50)
    except Exception:
        ids = []
    out = []
    for rid in ids:
        rid = rid.decode() if isinstance(rid, bytes) else rid
        raw = await redis.get(_run_key(rid))
        if not raw:
            continue
        st = json.loads(raw)
        out.append({
            "id": rid, "status": st.get("status"), "names": st.get("names") or [],
            "approved": st.get("approved", 0), "started_at": st.get("started_at"),
            "progress": st.get("progress", 0),
        })
    return {"investigations": out}


@router.get("/investigations/{run_id}")
async def get_investigation(
    run_id: str,
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
    session: AsyncSession = Depends(get_session),
) -> dict:
    raw = await redis.get(_run_key(run_id))
    if raw is None:
        raise HTTPException(status_code=404, detail="Investigation not found or expired.")
    st = json.loads(raw)
    # Live per-name dossiers from the current corpus (keep enriching as crawls land).
    dossiers = [await gather_dossier(session, n, as_name=True) for n in (st.get("names") or [])]
    return {
        "id": run_id, "status": st.get("status"), "progress": st.get("progress", 0),
        "names": st.get("names") or [], "approved": st.get("approved", 0),
        "new_domains": st.get("new_domains", 0), "evaluated": st.get("evaluated", 0),
        "onion_sources": st.get("onion_sources", 0), "onion_enabled": st.get("onion_enabled", False),
        "approved_list": st.get("approved_list", []),  # the actual domains/sources
        "dossiers": dossiers,
    }


@router.delete("/investigations/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_investigation(
    run_id: str,
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
) -> None:
    """Remove a discovery case (the run record + its list entry).

    Only drops the case folder from the dashboard — discovered Sources/Pages stay
    in the corpus (they may be shared across cases and feed future searches).
    """
    try:
        await redis.delete(_run_key(run_id))
        await redis.lrem(INVESTIGATIONS_KEY, 0, run_id)
    except Exception:
        pass


def _compose_case_summary(names: list[str], dossiers: list[dict]) -> str:
    lines = [f"Investigation of {', '.join(names) or 'subject(s)'} — potential public-OSINT findings, not confirmed."]
    for d in dossiers:
        c = d.get("counts") or {}
        bits = []
        if d.get("titles"):
            bits.append("role " + " / ".join(d["titles"][:2]))
        if d.get("orgs"):
            bits.append("org " + " / ".join(d["orgs"][:2]))
        if d.get("locations"):
            bits.append("in " + ", ".join(d["locations"][:3]))
        lines.append(
            f"• {d.get('term')}: {c.get('faces',0)} image(s), {c.get('phones',0)} phone(s), "
            f"{c.get('emails',0)} email(s), {c.get('pages',0)} page(s)"
            + (" — " + "; ".join(bits) if bits else "")
        )
    return "\n".join(lines)


@router.post("/investigations/{run_id}/summary")
async def investigation_summary(
    run_id: str,
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """AI case summary of an investigation from the public data gathered so far.
    Composed fallback when no AI provider is configured."""
    raw = await redis.get(_run_key(run_id))
    if raw is None:
        raise HTTPException(status_code=404, detail="Investigation not found or expired.")
    st = json.loads(raw)
    names = st.get("names") or []
    dossiers = [await gather_dossier(session, n, as_name=True) for n in names]

    from app.ai.router import AIMessage, get_ai_provider

    provider = get_ai_provider()
    if provider is None or not provider.available():
        return {"available": False, "summary": _compose_case_summary(names, dossiers), "model": None}

    # Compact context for the model (counts + extracted attributes + a few sources).
    ctx = {"names": names, "subjects": []}
    for d in dossiers:
        ctx["subjects"].append({
            "name": d.get("term"), "counts": d.get("counts"),
            "titles": d.get("titles"), "orgs": d.get("orgs"), "locations": d.get("locations"),
            "emails": (d.get("emails") or [])[:5], "phones": (d.get("phones") or [])[:5],
            "usernames": (d.get("usernames") or [])[:5],
            "pages": [p.get("title") or p.get("url") for p in (d.get("pages") or [])[:8]],
        })
    system = (
        "You are an OSINT analyst. Write a clear, well-organised CASE SUMMARY of the subject(s) "
        "from the PUBLIC data provided only — who they appear to be, roles/affiliations, locations, "
        "contactable identifiers found, and notable sources. Use short sections / bullet points. "
        "Do NOT invent facts. Hedge: 'appears to be' / 'potential', never a confirmed identity."
    )
    try:
        summary = await provider.chat(
            [AIMessage(role="system", content=system), AIMessage(role="user", content=json.dumps(ctx))]
        )
        return {"available": True, "summary": summary.strip(), "model": provider.name}
    except Exception:
        return {"available": False, "summary": _compose_case_summary(names, dossiers), "model": None}


@router.get("/public-searches")
async def public_searches(
    operator: User = Depends(get_current_operator),
    redis: Redis = Depends(get_redis),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """What public users searched + a live dossier of results for each term."""
    terms = await learning.list_terms(redis)
    out = []
    for t in terms[:40]:
        term = t.get("term")
        if not term:
            continue
        d = await gather_dossier(session, term)
        out.append({**t, "dossier": d})
    return {"searches": out}
