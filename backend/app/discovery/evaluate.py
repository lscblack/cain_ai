"""Evaluate a candidate domain: does it host useful public OSINT data?

Fetches the homepage (+ a couple of linked pages) via the crawler's SSRF-safe
fetcher, checks for images / phones / emails / usernames / robots / no-auth, and
produces a 0-100 source score. Fetcher + robots are injectable for tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.crawlers.extract import extract_contacts, extract_image_urls, extract_links
from app.crawlers.runner import Fetched

Fetcher = Callable[[str], Awaitable[Fetched]]
RobotsCheck = Callable[[str], Awaitable[bool]]


@dataclass
class Evaluation:
    domain: str
    base_url: str
    reachable: bool = False
    has_images: bool = False
    has_phones: bool = False
    has_emails: bool = False
    has_usernames: bool = False
    robots_ok: bool = True
    requires_auth: bool = False
    score: int = 0
    signals: list[str] = field(default_factory=list)
    approved: bool = False

    def to_dict(self) -> dict:
        return {
            "domain": self.domain, "base_url": self.base_url, "reachable": self.reachable,
            "has_images": self.has_images, "has_phones": self.has_phones,
            "has_emails": self.has_emails, "has_usernames": self.has_usernames,
            "robots_ok": self.robots_ok, "requires_auth": self.requires_auth,
            "score": self.score, "signals": self.signals, "approved": self.approved,
        }


_AUTH_HINTS = ("please log in", "sign in to continue", "login required", "403 forbidden", "access denied")


async def evaluate_domain(
    domain: str,
    *,
    fetch: Fetcher,
    robots: RobotsCheck | None = None,
    max_pages: int = 3,
) -> Evaluation:
    base = f"https://{domain}/"
    ev = Evaluation(domain=domain, base_url=base)

    if robots is not None:
        try:
            ev.robots_ok = await robots(base)
        except Exception:
            ev.robots_ok = True

    resp = await fetch(base)
    if resp.status != 200 or "html" not in (resp.content_type or ""):
        ev.signals.append(f"home status {resp.status}")
        return ev
    ev.reachable = True
    html = resp.body.decode("utf-8", "replace")

    # sample a couple of internal links too
    pages_html = [html]
    for link in extract_links(html, base, same_host_only=True)[: max_pages - 1]:
        try:
            r = await fetch(link)
            if r.status == 200 and "html" in (r.content_type or ""):
                pages_html.append(r.body.decode("utf-8", "replace"))
        except Exception:
            pass

    images = contacts_emails = contacts_phones = contacts_users = 0
    low_all = " ".join(h.lower() for h in pages_html)
    for h in pages_html:
        images += len(extract_image_urls(h, base))
        c = extract_contacts(h)
        contacts_emails += len(c["emails"])
        contacts_phones += len(c["phones"])
        contacts_users += len(c["usernames"])

    ev.has_images = images >= 3
    ev.has_phones = contacts_phones > 0
    ev.has_emails = contacts_emails > 0
    ev.has_usernames = contacts_users > 0
    ev.requires_auth = any(h in low_all for h in _AUTH_HINTS)

    # scoring
    score = 0
    if ev.reachable:
        score += 20; ev.signals.append("reachable")
    if ev.has_images:
        score += 25; ev.signals.append(f"images:{images}")
    if ev.has_phones:
        score += 20; ev.signals.append(f"phones:{contacts_phones}")
    if ev.has_emails:
        score += 15; ev.signals.append(f"emails:{contacts_emails}")
    if ev.has_usernames:
        score += 15; ev.signals.append(f"usernames:{contacts_users}")
    if ev.robots_ok:
        score += 5; ev.signals.append("robots_ok")
    if ev.requires_auth:
        score -= 15; ev.signals.append("auth_wall")
    ev.score = max(0, min(100, score))
    return ev
