"""Concurrent username presence checks across public platforms."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from app.intelligence.username.platforms import PLATFORMS, PLATFORMS_BY_KEY, Platform

_VALID_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._\-]{1,39}$", re.I)

# fetch(url) -> HTTP status code, or None when the request failed/unreachable.
Fetcher = Callable[[str], Awaitable[int | None]]


@dataclass
class UsernameHit:
    platform: str
    name: str
    username: str
    url: str
    status: str  # found | not_found | unknown | error
    http_status: int | None
    checked_at: str

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "name": self.name,
            "username": self.username,
            "url": self.url,
            "status": self.status,
            "http_status": self.http_status,
            "checked_at": self.checked_at,
        }


def is_valid_username(username: str) -> bool:
    return bool(_VALID_USERNAME.match(username or ""))


def _classify(http_status: int | None) -> str:
    if http_status is None:
        return "error"
    if http_status == 200:
        return "found"
    if http_status in (301, 302, 303, 307, 308):
        return "unknown"  # redirect — ambiguous without following
    if http_status in (404, 410):
        return "not_found"
    if http_status in (401, 403, 429):
        return "unknown"  # access-limited/rate-limited; do not assert
    return "unknown"


async def _check_one(platform: Platform, username: str, fetch: Fetcher) -> UsernameHit:
    url = platform.url_for(username)
    try:
        status_code = await fetch(url)
    except Exception:
        status_code = None
    return UsernameHit(
        platform=platform.key,
        name=platform.name,
        username=username,
        url=url,
        status=_classify(status_code),
        http_status=status_code,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


async def check_username(
    username: str,
    fetch: Fetcher,
    *,
    platform_keys: list[str] | None = None,
    concurrency: int = 6,
) -> list[UsernameHit]:
    platforms = (
        [PLATFORMS_BY_KEY[k] for k in platform_keys if k in PLATFORMS_BY_KEY]
        if platform_keys
        else PLATFORMS
    )
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(p: Platform) -> UsernameHit:
        async with sem:
            return await _check_one(p, username, fetch)

    return await asyncio.gather(*[_bounded(p) for p in platforms])
