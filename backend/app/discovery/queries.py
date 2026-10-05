"""Generate public search queries for source discovery.

Deterministic, no network. Turns a region/country + categories + targets into the
kind of queries an analyst would run to find image/contact-rich public sites.
"""
from __future__ import annotations

# High-value OSINT source sites to target by name, with the `site:` operator.
# Any publicly reachable platform that can host an individual's profile/portfolio.
_NAME_SITES = [
    # encyclopedic / knowledge
    "en.wikipedia.org", "wikidata.org", "wikitree.com",
    # code / dev
    "github.com", "gitlab.com", "bitbucket.org", "huggingface.co", "kaggle.com",
    "stackoverflow.com", "dev.to", "replit.com", "codepen.io", "npmjs.com", "pypi.org",
    # professional / business
    "linkedin.com/in", "crunchbase.com", "wellfound.com", "angel.co", "f6s.com",
    "producthunt.com", "opencorporates.com", "zoominfo.com", "theorg.com",
    # social
    "x.com", "twitter.com", "instagram.com", "facebook.com", "tiktok.com",
    "threads.net", "bsky.app", "mastodon.social", "reddit.com", "t.me", "vk.com",
    "pinterest.com", "tumblr.com", "snapchat.com",
    # media / creative portfolios
    "youtube.com", "vimeo.com", "medium.com", "substack.com", "behance.net",
    "dribbble.com", "artstation.com", "deviantart.com", "soundcloud.com",
    "500px.com", "flickr.com", "unsplash.com", "contently.com", "muckrack.com",
    # identity / bio hubs & personal-site hosts
    "about.me", "gravatar.com", "linktr.ee", "carrd.co", "notion.site",
    "github.io", "wordpress.com", "wixsite.com", "weebly.com", "webflow.io",
    "blogspot.com", "medium.com", "beacons.ai", "bio.link", "read.cv", "polywork.com",
    # academic / research
    "researchgate.net", "scholar.google.com", "orcid.org", "academia.edu",
    "ssrn.com", "arxiv.org", "semanticscholar.org", "dblp.org", "loop.frontiersin.org",
    # verification / keys
    "keybase.io", "gist.github.com",
]
# Free-text angles that surface portfolios / bios / personal sites / contact pages.
_NAME_ANGLES = [
    "portfolio", "personal website", "personal site", "official website", "homepage",
    "profile", "biography", "bio", "about", "CV", "resume", "curriculum vitae",
    "LinkedIn", "GitHub", "Wikipedia", "portfolio site", "my work", "projects",
    "photo", "headshot", "contact email", "phone number", "WhatsApp",
    "interview", "speaker", "keynote", "founder", "CEO", "author", "artist",
    "designer", "developer", "engineer", "team member", "staff", "faculty",
    "press", "news", "profile picture", "@gmail.com", "blog",
]


def name_deep_queries(names: list[str], *, per_name: int = 48) -> list[str]:
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

    # Split the per-name budget so both targeted sites AND free-text angles
    # (personal website / portfolio / bio) always get queried.
    angle_budget = min(len(_NAME_ANGLES), max(10, per_name // 4))
    site_budget = max(1, per_name - angle_budget)
    for raw in names:
        n = (raw or "").strip()
        if not n:
            continue
        quoted = f'"{n}"'
        for site in _NAME_SITES[:site_budget]:
            add(f"{quoted} site:{site}")
        for angle in _NAME_ANGLES[:angle_budget]:
            add(f"{quoted} {angle}")
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
