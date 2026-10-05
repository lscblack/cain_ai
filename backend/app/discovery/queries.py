"""Generate public search queries for source discovery.

Deterministic, no network. Turns a region/country + categories + targets into the
kind of queries an analyst would run to find image/contact-rich public sites.
"""
from __future__ import annotations

# High-value OSINT source sites to target by name, with the `site:` operator.
_NAME_SITES = [
    "en.wikipedia.org", "github.com", "linkedin.com/in", "x.com", "twitter.com",
    "instagram.com", "facebook.com", "youtube.com", "medium.com", "behance.net",
    "dribbble.com", "about.me", "gravatar.com", "researchgate.net", "scholar.google.com",
    "crunchbase.com", "angel.co", "keybase.io", "gitlab.com", "stackoverflow.com",
]
# Free-text angles that surface portfolios / bios / contact pages for a person.
_NAME_ANGLES = [
    "portfolio", "profile", "biography", "CV resume", "LinkedIn", "GitHub",
    "Wikipedia", "photo", "contact email", "phone", "about", "interview",
    "speaker", "founder", "author", "team member", "press",
]


def name_deep_queries(names: list[str], *, per_name: int = 26) -> list[str]:
    """Deep per-person queries across portfolios, Wikipedia, GitHub, socials, news.

    No network — these are the public-search strings the discovery engine then runs.
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        q = " ".join(q.split())
        if q and q not in seen:
            seen.add(q)
            out.append(q)

    for raw in names:
        n = (raw or "").strip()
        if not n:
            continue
        quoted = f'"{n}"'
        count = 0
        for site in _NAME_SITES:
            add(f"{quoted} site:{site}")
            count += 1
            if count >= per_name:
                break
        for angle in _NAME_ANGLES:
            if count >= per_name:
                break
            add(f"{quoted} {angle}")
            count += 1
    return out

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
            # Known targets expand to curated hints; custom/unlisted ones use the
            # literal term so operator-typed targets still drive discovery.
            hints = _TARGET_HINTS.get(t) or [f'"{t}"']
            for hint in hints:
                add(f"site:{tld} {hint}")
    # broad directory queries
    add(f"{label} business directory phone")
    add(f"{label} professional directory profiles")
    add(f"{label} talent directory photos")
    add(f"{label} public figures profiles")

    return queries[:limit]


def generate_queries_multi(
    countries: list[str],
    categories: list[str],
    targets: list[str],
    *,
    limit: int = 60,
) -> list[str]:
    """Combine per-country queries across several regions, deduped, capped."""
    countries = [c for c in (countries or []) if c and c.strip()] or ["rwanda"]
    # Per-country share keeps the combined set bounded as countries grow.
    per = max(8, limit // len(countries))
    out: list[str] = []
    seen: set[str] = set()
    for c in countries:
        for q in generate_queries(c, categories, targets, limit=per):
            if q not in seen:
                seen.add(q)
                out.append(q)
    return out[:limit]
