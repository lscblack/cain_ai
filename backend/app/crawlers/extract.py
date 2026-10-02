"""HTML extraction: image URLs and same-scope links. Pure, no network."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

_HREF_RE = re.compile(r"<a\b[^>]*?\bhref\s*=\s*[\"']([^\"']+)[\"']", re.I)

# src plus common lazy-load attributes used by news/CMS sites
_SRC_ATTRS = ("src", "data-src", "data-lazy-src", "data-original", "data-url", "data-image")
_SRC_RE = re.compile(
    r"\b(?:" + "|".join(_SRC_ATTRS) + r")\s*=\s*[\"']([^\"']+)[\"']", re.I
)
# srcset on <img> and <source> inside <picture>
_SRCSET_RE = re.compile(r"\b(?:srcset|data-srcset)\s*=\s*[\"']([^\"']+)[\"']", re.I)
# og:image / twitter:image meta
_META_IMG_RE = re.compile(
    r"<meta\b[^>]*?(?:property|name)\s*=\s*[\"'](?:og:image|twitter:image)[^\"']*[\"'][^>]*?\bcontent\s*=\s*[\"']([^\"']+)[\"']",
    re.I,
)

_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
_SKIP_HINTS = ("sprite", "logo", "icon", "favicon", "placeholder", "blank", "pixel", "avatar-default")


def extract_image_urls(html: str, base_url: str) -> list[str]:
    html = html or ""
    urls: list[str] = []
    for m in _SRC_RE.findall(html):
        urls.append(urljoin(base_url, m.strip()))
    for srcset in _SRCSET_RE.findall(html):
        for part in srcset.split(","):
            candidate = part.strip().split(" ")[0]
            if candidate:
                urls.append(urljoin(base_url, candidate))
    for m in _META_IMG_RE.findall(html):
        urls.append(urljoin(base_url, m.strip()))

    seen: list[str] = []
    for u in urls:
        if u in seen:
            continue
        low = u.lower()
        if low.startswith("data:"):
            continue
        path = urlsplit(low).path
        if any(h in low for h in _SKIP_HINTS):
            continue
        if path.endswith(_IMG_EXT) or "image" in path or "/media/" in low or "/uploads/" in low or "/photo" in low:
            seen.append(u)
    return seen


def extract_links(html: str, base_url: str, *, same_host_only: bool = True) -> list[str]:
    base_host = urlsplit(base_url).hostname
    out: list[str] = []
    for href in _HREF_RE.findall(html or ""):
        href = href.strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https"):
            continue
        if same_host_only and parts.hostname != base_host:
            continue
        clean = absolute.split("#")[0]
        if clean not in out:
            out.append(clean)
    return out


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_DESC_RE = re.compile(
    r"<meta\b[^>]*?(?:name|property)\s*=\s*[\"'](?:description|og:description)[\"'][^>]*?\bcontent\s*=\s*[\"']([^\"']+)[\"']",
    re.I,
)
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
_ALT_RE = re.compile(r"\balt\s*=\s*[\"']([^\"']+)[\"']", re.I)
_FIGCAPTION_RE = re.compile(r"<figcaption[^>]*>(.*?)</figcaption>", re.I | re.S)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
# A person-name-ish token: 2–3 capitalized words (allows apostrophes/hyphens)
_NAME_RE = re.compile(r"\b([A-Z][a-z'’\-]+(?:\s+[A-Z][a-z'’\-]+){1,2})\b")
_NAME_STOP = {
    "The New", "New Times", "Read More", "All Rights", "Rights Reserved", "Privacy Policy",
    "Terms Of", "Sign In", "Log In", "Home News", "United States", "New York", "Getty Images",
    "Prime Minister", "President Paul", "Click Here", "Our Team", "Contact Us",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG_STRIP_RE.sub(" ", text or "")).strip()


def extract_page_meta(html: str) -> dict:
    html = html or ""
    title = _clean(_TITLE_RE.search(html).group(1)) if _TITLE_RE.search(html) else None
    desc_m = _META_DESC_RE.search(html)
    description = _clean(desc_m.group(1)) if desc_m else None
    return {"title": title, "description": description}


def extract_person_names(html: str, *, limit: int = 15) -> list[str]:
    """Best-effort candidate person names from captions, alt text, and title.
    Noisy by nature — surfaced as 'possible names', never as confirmed identity."""
    html = html or ""
    sources: list[str] = []
    sources += [_clean(c) for c in _FIGCAPTION_RE.findall(html)]
    sources += _ALT_RE.findall(html)
    m = _TITLE_RE.search(html)
    if m:
        sources.append(_clean(m.group(1)))
    found: list[str] = []
    for s in sources:
        for cand in _NAME_RE.findall(s or ""):
            c = cand.strip()
            if c and c not in _NAME_STOP and c not in found and len(c) <= 40:
                found.append(c)
    return found[:limit]


def extract_images_with_context(html: str, base_url: str) -> list[dict]:
    """Return [{url, alt, caption}] — pairs each image with its alt text and the
    nearest following <figcaption>, so faces keep a human-readable label."""
    html = html or ""
    urls = extract_image_urls(html, base_url)
    url_set = {u for u in urls}

    # map absolute url -> alt (from the <img> tag that referenced it)
    alt_by_url: dict[str, str] = {}
    for tag in _IMG_TAG_RE.findall(html):
        alt_m = _ALT_RE.search(tag)
        if not alt_m:
            continue
        alt = _clean(alt_m.group(1))
        for src in _SRC_RE.findall(tag) + [p.strip().split(" ")[0] for ss in _SRCSET_RE.findall(tag) for p in ss.split(",")]:
            absu = urljoin(base_url, src.strip())
            if absu in url_set and absu not in alt_by_url:
                alt_by_url[absu] = alt

    captions = [_clean(c) for c in _FIGCAPTION_RE.findall(html)]
    # crude: if there is exactly one image and one caption, pair them
    default_caption = captions[0] if len(captions) == 1 and len(urls) == 1 else None

    out = []
    for u in urls:
        out.append({"url": u, "alt": alt_by_url.get(u), "caption": default_caption})
    return out


_EMAIL_RE = re.compile(r"\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b", re.I)
_HANDLE_RE = re.compile(r"(?<![\w@])@([a-z0-9_]{3,30})\b", re.I)
_EMAIL_SKIP = ("example.com", "sentry.io", "domain.com", "email.com", "yourdomain", "@2x", "@3x", ".png", ".jpg", ".webp", ".gif")
# CSS at-rules + generic path/handle words that are not real usernames
_USER_STOP = {
    "share", "intent", "home", "login", "sharer", "channel", "company", "user", "in",
    "keyframes", "media", "font", "font-face", "import", "supports", "charset", "page",
    "type", "context", "embed", "2x", "3x", "watch", "about", "help", "privacy", "terms",
    "profile", "pages", "groups", "hashtag", "explore", "search", "feed", "status",
}
# social profile URL -> username, reused for username extraction from links
_SOCIAL_RE = re.compile(
    r"https?://(?:www\.)?(?:twitter|x|instagram|facebook|tiktok|github|gitlab|linkedin|youtube|t|telegram|pinterest|reddit)\.com/(?:@|in/|user/)?([a-z0-9._\-]{2,40})",
    re.I,
)


def extract_contacts(html: str, *, region: str | None = None) -> dict:
    """Best-effort emails / phones / usernames from a page.
    Phones validated via libphonenumber (international + optional default region)."""
    html = html or ""
    text = _clean(html)

    emails: list[str] = []
    for m in _EMAIL_RE.findall(html):
        e = m.lower()
        if e not in emails and not any(s in e for s in _EMAIL_SKIP):
            emails.append(e)

    usernames: list[str] = []
    for u in _SOCIAL_RE.findall(html):
        u = u.strip().lower()
        if u and u not in usernames and u not in _USER_STOP:
            usernames.append(u)
    for h in _HANDLE_RE.findall(text):
        h = h.lower()
        if h not in usernames and h not in _USER_STOP:
            usernames.append(h)

    phones: list[str] = []
    try:
        import phonenumbers

        regions = [None] + ([region] if region else [])
        for reg in regions:
            for match in phonenumbers.PhoneNumberMatcher(text, reg):
                if phonenumbers.is_valid_number(match.number):
                    e164 = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
                    if e164 not in phones:
                        phones.append(e164)
    except Exception:
        pass

    return {"emails": emails[:50], "phones": phones[:50], "usernames": usernames[:50]}


def path_allowed(url: str, allowed: list[str], excluded: list[str]) -> bool:
    path = urlsplit(url).path or "/"
    if any(path.startswith(e) for e in excluded if e):
        return False
    if allowed:
        return any(path.startswith(a) for a in allowed)
    return True
