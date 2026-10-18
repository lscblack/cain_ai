"""Authorized-target enforcement for ACTIVE assessment operations.

Passive public-information gathering (DNS, WHOIS, headers, TLS) does not require
an entry here. Anything that actively probes a target (e.g. nmap) is refused
unless the operator has explicitly added the target to their authorized list.
Adding a target is an operator action in the UI/API — the model can never add
one itself.
"""
from __future__ import annotations

import ipaddress
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.security import AuthorizedTarget
from app.security import validate as V


def _norm_entry(entry: str) -> str:
    """Normalize a stored authorized-target entry to a bare host/IP or CIDR,
    so a URL ('https://x.com/') or host:port entry still matches a host."""
    entry = (entry or "").strip().lower().rstrip(".")
    if "://" in entry:
        from urllib.parse import urlsplit

        return (urlsplit(entry).hostname or "").rstrip(".")
    if "/" in entry:
        try:
            ipaddress.ip_network(entry, strict=False)
            return entry  # keep CIDR as-is
        except ValueError:
            return entry.split("/", 1)[0]  # host/path → host
    return entry


def _matches(target: str, entry: str) -> bool:
    target = target.strip().lower().rstrip(".")
    entry = _norm_entry(entry)
    if not entry:
        return False
    if target == entry:
        return True
    # CIDR entry containing the target IP
    if "/" in entry:
        try:
            net = ipaddress.ip_network(entry, strict=False)
            return ipaddress.ip_address(target) in net
        except ValueError:
            return False
    # a domain entry authorizes all of its subdomains
    if target.endswith("." + entry):
        return True
    return False


async def is_authorized(session: AsyncSession, user_id: uuid.UUID, target: str) -> bool:
    try:
        norm = V.target_host(target)
    except V.ArgError:
        return False
    rows = (
        await session.execute(
            select(AuthorizedTarget).where(
                AuthorizedTarget.user_id == user_id,
                AuthorizedTarget.active.is_(True),
            )
        )
    ).scalars().all()
    return any(_matches(norm, r.target) for r in rows)
