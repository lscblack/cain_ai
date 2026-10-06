"""Discovery run coordinator: discover -> qualify -> score -> approve -> crawl.

Progress is written to Redis so the UI can poll a run. Approved domains are added
as sources (deduped) and optionally queued for crawling.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

from redis.asyncio import Redis
from sqlalchemy import select

from app.core.logging import get_logger
from app.crawlers.http import RobotsGate, httpx_fetch
from app.crawlers.queue import enqueue_crawls
from app.database.models.source import Source
from app.database.session import async_session_maker
from app.discovery.evaluate import evaluate_domain
from app.discovery.queries import generate_queries_multi
from app.discovery.search import discover_candidates

logger = get_logger("kai.discovery")

RUN_KEY = "kai:discovery:run:{id}"
RUN_TTL = 60 * 60 * 24


def _run_key(run_id: str) -> str:
    return RUN_KEY.format(id=run_id)


async def _save(redis: Redis, run_id: str, state: dict) -> None:
    try:
        await redis.set(_run_key(run_id), json.dumps(state), ex=RUN_TTL)
    except Exception:
        pass


async def run_discovery(
    run_id: str,
    *,
    redis: Redis,
    countries: list[str] | None = None,
    country: str | None = None,  # back-compat: single country
    categories: list[str],
    targets: list[str],
    min_score: int = 60,
    max_domains: int = 200,
    auto_crawl: bool = False,
) -> None:
    countries = [c for c in (countries or ([country] if country else [])) if c] or ["rwanda"]
    state = {
        "id": run_id, "status": "searching", "countries": countries,
        "country": countries[0], "categories": categories,
        "targets": targets, "min_score": min_score, "max_domains": max_domains,
        "candidates": 0, "already_known": 0, "new_domains": 0, "evaluated": 0,
        "approved": 0, "rejected": 0, "current": None, "approved_list": [],
        "started_at": time.time(), "progress": 0,
    }
    await _save(redis, run_id, state)

    queries = generate_queries_multi(countries, categories, targets)
    await _execute(
        run_id, redis=redis, queries=queries, state=state,
        min_score=min_score, max_domains=max_domains, auto_crawl=auto_crawl,
    )


async def run_term_discovery(
    run_id: str,
    *,
    redis: Redis,
    terms: list[str],
    min_score: int = 55,
    max_domains: int = 60,
    auto_crawl: bool = True,
) -> None:
    """Self-learning path: discover sources for specific searched terms."""
    state = {
        "id": run_id, "status": "searching", "country": None, "categories": ["learning"],
        "targets": terms, "min_score": min_score, "max_domains": max_domains,
        "candidates": 0, "already_known": 0, "new_domains": 0, "evaluated": 0,
        "approved": 0, "rejected": 0, "current": None, "approved_list": [],
        "started_at": time.time(), "progress": 0, "kind": "learning",
    }
    await _save(redis, run_id, state)
    queries = term_queries(terms)
    await _execute(
        run_id, redis=redis, queries=queries, state=state,
        min_score=min_score, max_domains=max_domains, auto_crawl=auto_crawl,
    )


INVESTIGATIONS_KEY = "kai:discovery:investigations"  # recent investigation run ids


def expand_query_tips(tips: list[str], names: list[str]) -> list[str]:
    """Operator-supplied query tips. A tip with '{name}' is expanded per name; any
    other tip is run as a literal query. Lets the operator steer discovery the way
    they'd actually search ("{name}" Rwandan journalist, site:x.com "{name}", …)."""
    out: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        q = " ".join(q.split())
        if q and q not in seen:
            seen.add(q)
            out.append(q)

    for tip in tips or []:
        tip = (tip or "").strip()
        if not tip:
            continue
        if "{name}" in tip:
            for n in names:
                add(tip.replace("{name}", n))
        else:
            add(tip)
    return out


async def run_name_investigation(
    run_id: str,
    *,
    redis: Redis,
    names: list[str],
    queries: list[str] | None = None,
    auto_crawl: bool = True,
    max_domains: int = 150,
) -> None:
    """Batch investigation: discover + crawl sources for a list of names so KAI can
    surface the images/phones/emails/usernames that might belong to them. Per-name
    dossiers are computed live from the corpus by the API as crawls land.

    `queries` are optional operator query tips (see expand_query_tips)."""
    from app.discovery.onion import onion_available
    from app.discovery.queries import name_deep_queries

    names = [n.strip() for n in names if n and n.strip()]
    state = {
        "id": run_id, "status": "discovering", "kind": "investigation", "names": names,
        "targets": names, "min_score": 45, "max_domains": max_domains,
        "candidates": 0, "already_known": 0, "new_domains": 0, "evaluated": 0,
        "approved": 0, "rejected": 0, "current": None, "approved_list": [],
        "onion_sources": 0, "onion_enabled": onion_available(),
        "started_at": time.time(), "progress": 0,
    }
    await _save(redis, run_id, state)
    try:
        await redis.lpush(INVESTIGATIONS_KEY, run_id)
        await redis.ltrim(INVESTIGATIONS_KEY, 0, 199)
    except Exception:
        pass

    # 1) Dark web: find .onion sites for the names via Ahmia and queue Tor crawls.
    if onion_available():
        state["status"] = "searching dark web"
        await _save(redis, run_id, state)
        try:
            state["onion_sources"] = await discover_onion_for(
                names, redis=redis, auto_crawl=auto_crawl
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("onion phase failed: %s", exc)
        await _save(redis, run_id, state)

    # 2) Clearnet: deep per-person queries across portfolios, Wikipedia, GitHub,
    #    socials, news — discover, qualify and crawl. Capped to bound SerpAPI cost
    #    on large name batches (each query is one search call).
    # Operator tips run FIRST (they're the queries the operator knows return hits),
    # then the auto deep queries; combined and capped.
    tip_queries = expand_query_tips(queries or [], names)
    auto = name_deep_queries(names)
    final_queries = list(dict.fromkeys(tip_queries + auto))[:300]
    await _execute(
        run_id, redis=redis, queries=final_queries, state=state,
        min_score=45, max_domains=max_domains, auto_crawl=auto_crawl,
    )


def term_queries(terms: list[str], *, limit: int = 40) -> list[str]:
    """Literal public queries for arbitrary searched identifiers/names/text."""
    out: list[str] = []

    def add(q: str) -> None:
        q = " ".join(q.split())
        if q and q not in out:
            out.append(q)

    for t in terms:
        t = (t or "").strip()
        if not t:
            continue
        add(f'"{t}"')
        add(f"{t} profile")
        add(f"{t} photo")
        add(f"{t} contact")
    return out[:limit]


async def _execute(
    run_id: str,
    *,
    redis: Redis,
    queries: list[str],
    state: dict,
    min_score: int,
    max_domains: int,
    auto_crawl: bool,
) -> None:
    candidates = await discover_candidates(queries)
    state["candidates"] = len(candidates)
    state["status"] = "evaluating"
    await _save(redis, run_id, state)

    async with async_session_maker() as session:
        known = set(
            (await session.execute(select(Source.domain))).scalars().all()
        )
    state["already_known"] = sum(1 for d in candidates if d in known)
    new_domains = [d for d in candidates if d not in known][:max_domains]
    state["new_domains"] = len(new_domains)
    await _save(redis, run_id, state)

    robots = RobotsGate()
    total = max(1, len(new_domains))
    sem = asyncio.Semaphore(6)  # evaluate several candidates at once (all I/O-bound)
    lock = asyncio.Lock()
    done = {"n": 0}

    async def evaluate_one(domain: str) -> None:
        async with sem:
            try:
                ev = await evaluate_domain(domain, fetch=httpx_fetch, robots=robots.allowed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("evaluate failed for %s: %s", domain, exc)
                async with lock:
                    state["rejected"] += 1
                    state["evaluated"] += 1
                    done["n"] += 1
                return
            # Keep any reachable source that scores — an auth link on the page no
            # longer hard-rejects it (many portfolios/socials show public profiles
            # behind a soft login prompt); the score still penalises a real wall.
            approved = ev.reachable and ev.score >= min_score
            ev.approved = approved
            if approved:
                await _add_source(domain, ev.to_dict(), auto_crawl=auto_crawl, redis=redis)
            async with lock:
                state["evaluated"] += 1
                done["n"] += 1
                state["current"] = domain
                state["progress"] = round((done["n"] / total) * 100)
                if approved:
                    state["approved"] += 1
                    state["approved_list"] = ([ev.to_dict()] + state["approved_list"])[:50]
                    known.add(domain)
                else:
                    state["rejected"] += 1
                state["last"] = ev.to_dict()
            await _save(redis, run_id, state)

    await asyncio.gather(*[evaluate_one(d) for d in new_domains])

    state["status"] = "done"
    state["current"] = None
    state["progress"] = 100
    state["finished_at"] = time.time()
    await _save(redis, run_id, state)
    logger.info("discovery %s done: approved=%d rejected=%d", run_id, state["approved"], state["rejected"])


async def _add_source(domain: str, ev: dict, *, auto_crawl: bool, redis: Redis) -> None:
    async with async_session_maker() as session:
        exists = (await session.execute(select(Source.id).where(Source.domain == domain))).scalar_one_or_none()
        if exists is not None:
            return
        src = Source(
            name=domain, base_url=f"https://{domain}/", domain=domain,
            allowed_paths=[], excluded_paths=[], max_depth=1, max_pages=50,
            schedule="manual", category="discovered",
            priority="high" if ev.get("score", 0) >= 80 else "medium",
        )
        session.add(src)
        await session.flush()
        sid = src.id
        await session.commit()
    if auto_crawl:
        try:
            await enqueue_crawls(redis, [sid])
        except Exception:
            pass


async def _add_onion_source(url: str, *, auto_crawl: bool, redis: Redis) -> bool:
    """Add a discovered .onion URL as a source and (optionally) queue a Tor crawl."""
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    if not host.endswith(".onion"):
        return False
    async with async_session_maker() as session:
        exists = (await session.execute(select(Source.id).where(Source.domain == host))).scalar_one_or_none()
        if exists is not None:
            return False
        src = Source(
            name=host, base_url=url if url.startswith("http") else f"http://{host}/",
            domain=host, allowed_paths=[], excluded_paths=[], max_depth=1, max_pages=40,
            schedule="manual", category="onion", priority="medium",
        )
        session.add(src)
        await session.flush()
        sid = src.id
        await session.commit()
    if auto_crawl:
        try:
            await enqueue_crawls(redis, [sid])
        except Exception:
            pass
    return True


async def discover_onion_for(names: list[str], *, redis: Redis, auto_crawl: bool, per_name: int = 12) -> int:
    """Search Ahmia for each name and add the resulting .onion sites as sources."""
    from app.discovery.onion import onion_available, search_onion

    if not onion_available():
        return 0
    added = 0
    for name in names:
        try:
            for url in await search_onion(name, limit=per_name):
                if await _add_onion_source(url, auto_crawl=auto_crawl, redis=redis):
                    added += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("onion discovery failed for %r: %s", name, exc)
    return added


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


async def mark_queued(redis: Redis, run_id: str, params: dict) -> None:
    """Write an initial 'queued' state so the UI can poll before the worker starts."""
    state = {
        "id": run_id, "status": "queued", "progress": 0,
        "candidates": 0, "already_known": 0, "new_domains": 0, "evaluated": 0,
        "approved": 0, "rejected": 0, "current": None, "approved_list": [],
        "started_at": time.time(),
        **{k: params.get(k) for k in ("countries", "country", "categories", "targets", "min_score", "max_domains")},
    }
    await _save(redis, run_id, state)
