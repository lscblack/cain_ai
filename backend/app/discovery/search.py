"""Collect candidate site domains from public web search.

Uses SerpAPI (Google) when a key is configured and has budget; otherwise spreads
the queries across several keyless engines (DuckDuckGo, Mojeek, SearXNG public
instances) round-robin so no single engine is hammered — this both widens coverage
and avoids per-engine rate limiting. Any engine that fails/ rate-limits is just
skipped for that query. HTTP getters are injectable for offline tests.
"""
from __future__ import annotations

import asyncio
import re
from typing import Awaitable, Callable
from urllib.parse import quote, unquote, urlsplit

from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger("kai.discovery.search")

TextGet = Callable[[str], Awaitable[str]]

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
# Wikimedia's robot policy rejects browser UA strings from datacenter IPs; it
# wants a descriptive agent with a contact. Used for the keyless Wikipedia API.
_WIKI_UA = "KAI-OSINT/1.0 (OSINT research tool; local, public pages only; contact tech@nexventures.net)"

# DuckDuckGo HTML result links wrap the target in ...?uddg=<urlencoded>
_DDG_UDDG_RE = re.compile(r"uddg=([^&\"']+)")
_DDG_HREF_RE = re.compile(r'class="result__a"[^>]*href="([^"]+)"', re.I)
# Mojeek result title links
_MOJEEK_RE = re.compile(r'<a\b[^>]*class="[^"]*\b(?:title|ob)\b[^"]*"[^>]*href="(https?://[^"]+)"', re.I)
_MOJEEK_RE2 = re.compile(r'<a\b[^>]*href="(https?://[^"]+)"[^>]*class="[^"]*\b(?:title|ob)\b[^"]*"', re.I)

# Public SearXNG instances that (sometimes) expose format=json. Best-effort; rotated.
_SEARX_INSTANCES = [
    "https://searx.be", "https://search.inetol.net", "https://searx.tiekoetter.com",
    "https://search.rhscz.eu", "https://baresearch.org", "https://opnxng.com",
]




def _tor_proxy() -> str | None:
    return get_settings().tor_socks_proxy or None


# DuckDuckGo's official onion — reachable only over Tor, served by rotating exit
# circuits, so it doesn't IP-rate-limit the way the clearnet endpoint does.
_DDG_ONION = "https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/html/"


async def _get_text(url: str, *, timeout: float = 20.0) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


async def _ddg_onion_post(query: str) -> str:
    """Search DuckDuckGo via its Tor onion (POST). Rate-limit resistant."""
    import httpx

    proxy = _tor_proxy()
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, proxy=proxy,
                                 headers={"User-Agent": "Mozilla/5.0"}) as client:
        r = await client.post(_DDG_ONION, data={"q": query})
        r.raise_for_status()
        return r.text


async def _get_json(url: str, *, timeout: float = 20.0) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


def search_available() -> bool:
    # Always available: SerpAPI when keyed+funded, else the keyless engine pool.
    return True




def _domain(url: str) -> str | None:
    try:
        host = urlsplit(url).hostname
        return host.lower().lstrip("www.") if host else None
    except Exception:
        return None


# ── Keyless engine parsers (pure) ────────────────────────────────────────────

def _ddg_links(html: str) -> list[str]:
    urls: list[str] = []
    for href in _DDG_HREF_RE.findall(html):
        m = _DDG_UDDG_RE.search(href)
        target = unquote(m.group(1)) if m else href
        if target.startswith("//"):
            target = "https:" + target
        if target.startswith("http"):
            urls.append(target)
    if not urls:
        for enc in _DDG_UDDG_RE.findall(html):
            urls.append(unquote(enc))
    return urls


def _mojeek_links(html: str) -> list[str]:
    urls = _MOJEEK_RE.findall(html) + _MOJEEK_RE2.findall(html)
    return [u for u in urls if "mojeek.com" not in u]


def _searx_results(data: dict) -> list[str]:
    return [r.get("url") for r in (data.get("results") or []) if r.get("url")]


# ── Keyless engines (async; use module getters, monkeypatched in tests) ──────

async def _eng_duckduckgo(q: str) -> list[str]:
    # Clearnet first (fast ~1s). If it's empty/blocked (rate-limited 202) and Tor is
    # available, fall back to the DDG onion (slow but rotating exits dodge the block).
    try:
        links = _ddg_links(await _get_text(f"https://html.duckduckgo.com/html/?q={quote(q)}", timeout=3.0))
        if links:
            return links
    except Exception:
        pass  # clearnet blocked/unreachable — fall through to the onion quickly
    if _tor_proxy():
        try:
            return _ddg_links(await _ddg_onion_post(q))
        except Exception:
            pass
    return []


async def _eng_mojeek(q: str) -> list[str]:
    return _mojeek_links(await _get_text(f"https://www.mojeek.com/search?q={quote(q)}"))


_searx_rr = 0


def _searx_instances() -> list[str]:
    # A self-hosted instance (reliable, unlimited JSON) is tried first; public
    # instances are a best-effort fallback.
    conf = get_settings().searxng_url.strip().rstrip("/")
    return ([conf] if conf else []) + _SEARX_INSTANCES


async def _eng_searxng(q: str) -> list[str]:
    """Open-source SearXNG metasearch JSON API (docs.searxng.org/dev/search_api).
    Tries the configured self-hosted instance first, then public instances."""
    global _searx_rr
    instances = _searx_instances()
    # one configured call, else rotate through a couple of public instances
    tries = instances[:1] if get_settings().searxng_url.strip() else instances
    for i in range(max(1, len(tries))):
        inst = tries[(_searx_rr + i) % len(tries)]
        _searx_rr += 1
        try:
            data = await _get_json(f"{inst}/search?q={quote(q)}&format=json&safesearch=0", timeout=9.0)
            urls = _searx_results(data)
            if urls:
                return urls
        except Exception:
            continue
    return []


async def _eng_wikipedia(q: str) -> list[str]:
    """Wikipedia's keyless opensearch API — a reliable PRIMARY source for named
    subjects. Returns the matching article URL(s); the crawler fetches them via
    Wikipedia's REST API (the /wiki/ page blocks bots, the API does not)."""
    import httpx

    try:
        url = (
            f"https://en.wikipedia.org/w/api.php?action=opensearch&limit=3"
            f"&namespace=0&redirects=resolve&search={quote(q)}&format=json"
        )
        async with httpx.AsyncClient(
            timeout=9.0, follow_redirects=True, headers={"User-Agent": _WIKI_UA}
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
        # opensearch returns [query, [titles], [descs], [urls]]
        if isinstance(data, list) and len(data) >= 4 and isinstance(data[3], list):
            return [u for u in data[3] if u]
    except Exception:
        pass
    return []


def _ordered_engines() -> list[tuple[str, Callable[[str], Awaitable[list[str]]]]]:
    """Engines in priority order. DuckDuckGo-over-Tor is the reliable workhorse
    (rotating Tor exits, no IP rate-limit); SearXNG is tried next *only* when a
    query returns nothing (its upstreams get suspended under load), then Mojeek.
    Reads FREE_ENGINES by name so tests can override the engine set."""
    by_name = dict(FREE_ENGINES)
    has_searx = bool(get_settings().searxng_url.strip())
    out: list[tuple[str, Callable[[str], Awaitable[list[str]]]]] = []
    seen: set[str] = set()

    def add(n: str) -> None:
        if n in by_name and n not in seen and not (n == "searxng" and not has_searx):
            out.append((n, by_name[n]))
            seen.add(n)

    add("duckduckgo")
    add("searxng")
    add("mojeek")
    for n, _ in FREE_ENGINES:
        add(n)
    return out


async def wikipedia_article(name: str) -> tuple[str, str] | None:
    """Keyless lookup of a subject's Wikipedia article → (url, title). The crawler
    fetches the article via Wikipedia's REST API (the /wiki/ page blocks bots)."""
    urls = await _eng_wikipedia(name)
    if not urls:
        return None
    url = urls[0]
    title = url.rstrip("/").rsplit("/", 1)[-1].replace("_", " ")
    from urllib.parse import unquote

    return url, unquote(title)


FREE_ENGINES: list[tuple[str, Callable[[str], Awaitable[list[str]]]]] = [
    ("duckduckgo", _eng_duckduckgo),
    ("searxng", _eng_searxng),
    ("mojeek", _eng_mojeek),
]


async def search_candidates_free(queries: list[str], *, concurrency: int = 12, delay: float = 0.0) -> dict[str, str]:
    """Per-query engine fallback: each query is tried on the reliable engine first,
    then the next only if it returned nothing — so a dead/suspended engine never
    starves a query of results. Workers run concurrently over a shared queue."""
    engines = _ordered_engines()
    work: asyncio.Queue = asyncio.Queue()
    for q in queries:
        work.put_nowait(q)

    found: dict[str, str] = {}
    lock = asyncio.Lock()
    # circuit breaker: an engine with 0 hits and >=4 misses/errors is 'dead' for
    # the rest of the run (e.g. SearXNG when all its upstreams are suspended).
    hits: dict[str, int] = {}
    miss: dict[str, int] = {}
    dead: set[str] = set()

    def is_dead(name: str) -> bool:
        return name in dead or (hits.get(name, 0) == 0 and miss.get(name, 0) >= 4)

    async def worker() -> None:
        while True:
            try:
                q = work.get_nowait()
            except asyncio.QueueEmpty:
                return
            for name, fn in engines:
                if is_dead(name):
                    if name not in dead:
                        dead.add(name)
                        logger.info("discovery: dropping engine %s (no results)", name)
                    continue
                try:
                    urls = await fn(q)
                except Exception:
                    miss[name] = miss.get(name, 0) + 1
                    continue
                if not urls:
                    miss[name] = miss.get(name, 0) + 1
                    continue
                hits[name] = hits.get(name, 0) + 1
                async with lock:
                    for u in urls:
                        dom = _domain(u or "")
                        if dom and not dom.endswith(("duckduckgo.com", "mojeek.com", "google.com")) and dom not in found:
                            found[dom] = f"https://{dom}/"
                break  # got results for this query — don't hit slower fallbacks
            if delay:
                await asyncio.sleep(delay)

    await asyncio.gather(*[worker() for _ in range(max(1, concurrency))])
    return found


# Back-compat: DuckDuckGo-only, with an injectable text getter (used by tests).
async def search_candidates_ddg(
    queries: list[str], *, max_queries: int = 60, http_get_text: TextGet | None = None, delay: float = 0.8
) -> dict[str, str]:
    getter = http_get_text or _get_text
    found: dict[str, str] = {}
    for i, q in enumerate(queries[:max_queries]):
        try:
            html = await getter(f"https://html.duckduckgo.com/html/?q={quote(q)}")
        except Exception:
            if http_get_text is None:
                await asyncio.sleep(delay)
            continue
        for link in _ddg_links(html):
            dom = _domain(link)
            if dom and not dom.endswith("duckduckgo.com") and dom not in found:
                found[dom] = f"https://{dom}/"
        if http_get_text is None and i < len(queries) - 1:
            await asyncio.sleep(delay)
    return found


async def discover_candidates(queries: list[str], *, per_query: int = 10) -> dict[str, str]:
    """Fully keyless discovery: the Tor/DuckDuckGo engine pool only — no API keys."""
    found = await search_candidates_free(queries)
    if found:
        logger.info("discovery: keyless engine pool found %d domains", len(found))
    return found
