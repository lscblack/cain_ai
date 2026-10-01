"""unavatar.io avatar resolution (https://unavatar.io).

Resolves a username (optionally per provider), email, or domain to an avatar
image. Used to turn username/email OSINT into face-index entries. Free tier is
25 requests/day per IP; an optional UNAVATAR_API_KEY raises that.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.net import UnsafeUrlError, validate_public_url

BASE = "https://unavatar.io"

# KAI platform key -> unavatar provider slug
PROVIDER_MAP = {
    "github": "github",
    "gitlab": "gitlab",
    "reddit": "reddit",
    "instagram": "instagram",
    "tiktok": "tiktok",
    "youtube": "youtube",
    "twitch": "twitch",
    "pinterest": "pinterest",
    "medium": "substack",  # unavatar has no medium; substack close-ish, kept distinct below
    "telegram": "telegram",
    "steam": "steam",
    "soundcloud": "soundcloud",
    "x": "x",
    "twitter": "twitter",
}


def avatar_url(identifier: str, provider: str | None = None, *, fallback: bool = False) -> str:
    """Build the unavatar URL. provider=None resolves by email/username/domain."""
    path = f"{provider}/{identifier}" if provider else identifier
    url = f"{BASE}/{path}"
    params = []
    if not fallback:
        params.append("fallback=false")
    key = get_settings().unavatar_api_key
    if key:
        params.append(f"token={key}")
    if params:
        url += "?" + "&".join(params)
    return url


async def fetch_avatar(identifier: str, provider: str | None = None) -> bytes | None:
    """Download the resolved avatar image bytes, or None if none/unavailable."""
    url = avatar_url(identifier, provider, fallback=False)
    try:
        validate_public_url(url.split("?")[0])
    except UnsafeUrlError:
        return None
    import httpx

    headers = {}
    key = get_settings().unavatar_api_key
    if key:
        headers["x-api-key"] = key
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            ctype = resp.headers.get("content-type", "")
            if not ctype.startswith("image/"):
                return None
            data = resp.content
            return data if data and len(data) < 10 * 1024 * 1024 else None
    except Exception:
        return None
