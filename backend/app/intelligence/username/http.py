"""Real HTTP fetcher for username checks (SSRF-guarded, read-only GET)."""
from __future__ import annotations

import httpx

from app.core.net import UnsafeUrlError, validate_public_url

_UA = "KAI-OSINT/0.1 (+local research; respects robots and public pages only)"


async def httpx_fetch(url: str) -> int | None:
    """GET a public profile URL and return its HTTP status, or None on failure.

    Validates the URL against SSRF rules first. Follows redirects so that a
    canonicalizing 301 doesn't read as a false negative.
    """
    try:
        validate_public_url(url)
    except UnsafeUrlError:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=8.0,
            follow_redirects=True,
            headers={"User-Agent": _UA, "Accept": "text/html"},
        ) as client:
            resp = await client.get(url)
            return resp.status_code
    except Exception:
        return None
