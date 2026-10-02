"""Generate public search queries for source discovery.

Deterministic, no network. Turns a region/country + categories + targets into the
kind of queries an analyst would run to find image/contact-rich public sites.
"""
from __future__ import annotations

# country -> (search label, ccTLD)
_COUNTRIES = {
    "rwanda": ("Rwanda", ".rw"),
    "kenya": ("Kenya", ".co.ke"),
    "uganda": ("Uganda", ".ug"),
    "tanzania": ("Tanzania", ".co.tz"),
    "nigeria": ("Nigeria", ".ng"),
    "ethiopia": ("Ethiopia", ".et"),
    "ghana": ("Ghana", ".gh"),
    "south africa": ("South Africa", ".co.za"),
    "africa": ("Africa", ""),
}

_CATEGORY_TERMS = {
    "people": ["public profiles", "team members", "staff directory", "about us team", "speakers"],
    "phone": ["phone directory", "contact us phone", "business directory phone", '"WhatsApp"'],
    "username": ["social profiles", "team social media", "member profiles", "author profiles"],
    "images": ["photographers", "talent directory", "event photos", "gallery people", "portfolio"],
    "business": ["business directory", "company directory", "yellow pages"],
    "news": ["news people", "journalists", "newspaper"],
}

_TARGET_HINTS = {
    "phone": ['"Phone"', '"Tel"', '"WhatsApp"', '"call us"'],
    "email": ['"email"', '"contact us"', '"@gmail.com"'],
    "username": ['"follow us"', '"Instagram"', '"Twitter"', '"LinkedIn"'],
    "images": ["photos", "gallery", "profile picture"],
}


def generate_queries(
    country: str,
    categories: list[str],
    targets: list[str],
    *,
    limit: int = 30,
) -> list[str]:
    label, tld = _COUNTRIES.get((country or "").strip().lower(), (country or "", ""))
    queries: list[str] = []

    def add(q: str) -> None:
        q = " ".join(q.split())
        if q and q not in queries:
            queries.append(q)

    cats = [c.lower() for c in categories] or ["people", "phone", "images"]
    tgts = [t.lower() for t in targets] or ["phone", "username", "images"]

    for cat in cats:
        for term in _CATEGORY_TERMS.get(cat, [cat]):
            add(f"{label} {term}")
    # site:ccTLD operator queries targeting the identifiers we want
    if tld:
        for t in tgts:
            for hint in _TARGET_HINTS.get(t, []):
                add(f"site:{tld} {hint}")
    # broad directory queries
    add(f"{label} business directory phone")
    add(f"{label} professional directory profiles")
    add(f"{label} talent directory photos")
    add(f"{label} public figures profiles")

    return queries[:limit]
