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


async def _get_text(url: str) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": _UA}) as client:
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


async def _get_json(url: str) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": _UA}) as client:
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
    # Prefer the Tor onion (no IP rate-limit); fall back to the clearnet endpoint.
    if _tor_proxy():
        try:
            return _ddg_links(await _ddg_onion_post(q))
        except Exception:
            pass
    return _ddg_links(await _get_text(f"https://html.duckduckgo.com/html/?q={quote(q)}"))


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
            data = await _get_json(f"{inst}/search?q={quote(q)}&format=json&safesearch=0")
            urls = _searx_results(data)
            if urls:
                return urls
        except Exception:
            continue
    return []


def _active_engines() -> list[tuple[str, Callable[[str], Awaitable[list[str]]]]]:
    """The engine rotation. A self-hosted SearXNG (open-source, aggregates many
    engines) is weighted highest when configured."""
    engines = list(FREE_ENGINES)
    if get_settings().searxng_url.strip():
        engines = [("searxng", _eng_searxng), ("searxng", _eng_searxng)] + engines
    return engines


FREE_ENGINES: list[tuple[str, Callable[[str], Awaitable[list[str]]]]] = [
    ("duckduckgo", _eng_duckduckgo),
    ("mojeek", _eng_mojeek),
    ("searxng", _eng_searxng),
]


async def search_candidates_free(queries: list[str], *, delay: float = 1.0) -> dict[str, str]:
    """Spread queries round-robin across the keyless engines (concurrently), so each
    engine handles ~1/N of them and no single one gets rate limited. Merge domains."""
    engines = _active_engines()  # a self-hosted SearXNG is weighted higher here
    rotation = [name for name, _ in engines]
    fn_by_name = {name: fn for name, fn in engines}
    buckets: dict[str, list[str]] = {name: [] for name in fn_by_name}
    for i, q in enumerate(queries):
        buckets[rotation[i % len(rotation)]].append(q)

    found: dict[str, str] = {}
    lock = asyncio.Lock()

    async def run(name: str, fn: Callable[[str], Awaitable[list[str]]], qs: list[str]) -> None:
        # A few concurrent requests per engine — fine for the Tor onion (no IP
        # rate-limit) and mild for the clearnet ones. Drop an engine that keeps failing.
        sem = asyncio.Semaphore(3)
        fails = {"n": 0}
        stop = asyncio.Event()

        async def one(q: str) -> None:
            if stop.is_set():
                return
            async with sem:
                try:
                    urls = await fn(q)
                except Exception as exc:  # noqa: BLE001
                    fails["n"] += 1
                    logger.debug("%s failed: %s", name, exc)
                    if fails["n"] >= 4:
                        stop.set()
                        logger.info("discovery: dropping engine %s (repeated failures)", name)
                    return
                async with lock:
                    for u in urls:
                        dom = _domain(u or "")
                        if dom and not dom.endswith(("duckduckgo.com", "mojeek.com")) and dom not in found:
                            found[dom] = f"https://{dom}/"
                if delay:
                    await asyncio.sleep(delay)

        await asyncio.gather(*[one(q) for q in qs])

    await asyncio.gather(*[run(n, fn_by_name[n], buckets[n]) for n in buckets if buckets[n]])
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
