"""Generate public search queries for source discovery.

Deterministic, no network. Turns a region/country + categories + targets into the
kind of queries an analyst would run to find image/contact-rich public sites.
"""
from __future__ import annotations

# High-value OSINT source sites to target by name, with the `site:` operator.
# Any publicly reachable platform that can host an individual's profile/portfolio.
_NAME_SITES = [
    # the highest-value first 10 (used by default) — where people most often appear
    "en.wikipedia.org", "linkedin.com/in", "github.com", "x.com", "instagram.com",
    "facebook.com", "medium.com", "youtube.com", "about.me", "github.io",
    # encyclopedic / knowledge
    "wikidata.org", "wikitree.com",
    # code / dev
    "gitlab.com", "bitbucket.org", "huggingface.co", "kaggle.com",
    "stackoverflow.com", "dev.to", "replit.com", "codepen.io", "npmjs.com", "pypi.org",
    # professional / business
    "crunchbase.com", "wellfound.com", "angel.co", "f6s.com",
    "producthunt.com", "opencorporates.com", "zoominfo.com", "theorg.com",
    # social
    "twitter.com", "tiktok.com",
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

# Life-event / freshness angles: always run (independent of angle_budget) so the
# index keeps recent public status — appointments, awards, legal news, and, yes,
# whether/when the person died. Public-record signals only.
_LIFE_ANGLES = [
    "obituary", "died", "death", "passed away", "funeral",
    "date of birth", "born", "age",
    "latest news", "recent news", "current role", "today",
    "appointed", "award", "arrested", "sentenced", "statement",
]

# Family angles — public relations only (surfaces relatives for the graph).
_FAMILY_ANGLES = [
    "wife", "husband", "spouse", "children", "son", "daughter",
    "family", "parents", "married", "siblings",
]


def name_deep_queries(
    names: list[str], *, site_budget: int = 10, angle_budget: int = 16, life_budget: int = 16
) -> list[str]:
    """Per-person queries for discovery.

    Leads with the broad, productive queries (bare name, quoted name, name + a few
    angles) that keyless engines actually return results for, then a *small* set of
    `site:` queries (those mostly return nothing outside Google and just slow things
    down). No network — these are the public-search strings the engine then runs.
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
        add(n)        # broad
        add(quoted)   # exact phrase
        for angle in _NAME_ANGLES[:angle_budget]:
            add(f"{n} {angle}")
        # Life-event / freshness angles use the exact-phrase name to stay on-subject.
        for angle in _LIFE_ANGLES[:life_budget]:
            add(f"{quoted} {angle}")
        for angle in _FAMILY_ANGLES:
            add(f"{quoted} {angle}")
        for site in _NAME_SITES[:site_budget]:
            add(f"{quoted} site:{site}")
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
