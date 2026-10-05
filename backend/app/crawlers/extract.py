"""HTML extraction: image URLs and same-scope links. Pure, no network."""
from __future__ import annotations

import html as _html
import json
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
# explicit mailto: / tel: links — the most reliable contact signal
_MAILTO_RE = re.compile(r"mailto:([^\"'?>\s]+)", re.I)
_TEL_RE = re.compile(r"tel:(\+?[0-9().\-\s]{6,20})", re.I)

# ccTLD -> default phone region, so local-format numbers (0788…) parse, not just +…
_TLD_REGION = {
    "rw": "RW", "ke": "KE", "ug": "UG", "tz": "TZ", "ng": "NG", "et": "ET",
    "gh": "GH", "za": "ZA", "ma": "MA", "eg": "EG", "sn": "SN", "ci": "CI",
    "cm": "CM", "zm": "ZM", "zw": "ZW", "bw": "BW", "mw": "MW", "mz": "MZ",
    "uk": "GB", "us": "US", "ca": "CA", "fr": "FR", "de": "DE", "in": "IN",
}


def region_for_host(host: str | None) -> str | None:
    """Guess a default phone region from a hostname's TLD (e.g. igihe.rw -> RW)."""
    if not host:
        return None
    parts = host.lower().rsplit(".", 2)
    tld = parts[-1]
    # handle second-level domains like co.ke / co.za
    if len(parts) >= 2 and parts[-2] in ("co", "or", "ac", "go", "com", "net", "org"):
        return _TLD_REGION.get(tld) or _TLD_REGION.get(parts[-2])
    return _TLD_REGION.get(tld)
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
    # mailto: links first (most reliable), then any plain-text / inline emails
    for m in list(_MAILTO_RE.findall(html)) + list(_EMAIL_RE.findall(html)):
        e = m.split("?")[0].strip().lower()
        if _EMAIL_RE.fullmatch(e) and e not in emails and not any(s in e for s in _EMAIL_SKIP):
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

        # Scan the page text AND explicit tel: links, under both international (None)
        # and the site's default region so local-format numbers (0788…) also parse.
        tel_text = " ".join(_TEL_RE.findall(html))
        haystacks = [text, tel_text]
        regions = [None] + ([region] if region else [])
        for reg in regions:
            for hay in haystacks:
                if not hay:
                    continue
                for match in phonenumbers.PhoneNumberMatcher(hay, reg):
                    if phonenumbers.is_valid_number(match.number):
                        e164 = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
                        if e164 not in phones:
                            phones.append(e164)
    except Exception:
        pass

    return {"emails": emails[:50], "phones": phones[:50], "usernames": usernames[:50]}


_LDJSON_RE = re.compile(
    r'<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S
)
_META_RE = re.compile(
    r'<meta\b[^>]*?(?:property|name)\s*=\s*["\']([^"\']+)["\'][^>]*?content\s*=\s*["\']([^"\']*)["\']', re.I
)
_PERSON_TYPES = {"person"}
_ORG_TYPES = {"organization", "corporation", "ngo", "educationalorganization",
              "newsmediaorganization", "localbusiness", "governmentorganization"}


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _addr_str(addr) -> str | None:
    if isinstance(addr, str):
        return _html.unescape(addr).strip() or None
    if isinstance(addr, dict):
        parts = [addr.get(k) for k in (
            "streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")]
        parts = [p if isinstance(p, str) else (p.get("name") if isinstance(p, dict) else None) for p in parts]
        s = ", ".join(p.strip() for p in parts if p)
        return s or None
    return None


def _walk_ldjson(node, out: dict) -> None:
    """Pull people/org/contact/location fields out of a JSON-LD node (recursively)."""
    if isinstance(node, list):
        for n in node:
            _walk_ldjson(n, out)
        return
    if not isinstance(node, dict):
        return
    for key in ("@graph", "mainEntity", "author", "creator", "publisher", "itemListElement"):
        if key in node:
            _walk_ldjson(node[key], out)

    types = [t.lower() for t in _as_list(node.get("@type")) if isinstance(t, str)]
    name = node.get("name")
    if isinstance(name, str) and name.strip():
        if any(t in _PERSON_TYPES for t in types):
            out["names"].add(name.strip())
        elif any(t in _ORG_TYPES for t in types):
            out["orgs"].add(name.strip())

    for t in _as_list(node.get("jobTitle")):
        if isinstance(t, str) and t.strip():
            out["titles"].add(t.strip())
    for w in _as_list(node.get("worksFor")) + _as_list(node.get("affiliation")) + _as_list(node.get("memberOf")):
        nm = w.get("name") if isinstance(w, dict) else (w if isinstance(w, str) else None)
        if nm:
            out["orgs"].add(nm.strip())
    for e in _as_list(node.get("email")):
        if isinstance(e, str):
            out["emails"].add(e.replace("mailto:", "").strip().lower())
    for p in _as_list(node.get("telephone")):
        if isinstance(p, str) and p.strip():
            out["phones_raw"].add(p.strip())
    for s in _as_list(node.get("sameAs")):
        if isinstance(s, str) and s.startswith("http"):
            out["social"].add(s.strip())
    for locked in ("address", "location", "homeLocation", "workLocation", "birthPlace", "areaServed"):
        for loc in _as_list(node.get(locked)):
            a = _addr_str(loc.get("address") if isinstance(loc, dict) and "address" in loc else loc)
            if a:
                out["locations"].add(a)


def extract_structured(html: str) -> dict:
    """schema.org JSON-LD + OpenGraph/meta → people, titles, orgs, locations, socials.

    The richest 'map of a target': many sites embed a Person/Organization with
    jobTitle, worksFor, address, telephone, email and sameAs social links.
    """
    html = html or ""
    out = {k: set() for k in ("names", "titles", "orgs", "locations", "social",
                              "emails", "phones_raw", "descriptions")}
    for block in _LDJSON_RE.findall(html):
        txt = block.strip()
        try:
            data = json.loads(txt)
        except Exception:
            continue
        _walk_ldjson(data, out)

    # OpenGraph / meta
    og: dict[str, str] = {}
    for prop, content in _META_RE.findall(html):
        og[prop.lower()] = _html.unescape(content).strip()
    if og.get("og:type") == "profile":
        nm = " ".join(x for x in (og.get("profile:first_name"), og.get("profile:last_name")) if x).strip()
        if nm:
            out["names"].add(nm)
    for k in ("og:description", "description"):
        if og.get(k):
            out["descriptions"].add(og[k])
    if og.get("og:site_name"):
        out["orgs"].add(og["og:site_name"])

    return {k: sorted(v)[:20] for k, v in out.items()}


def enrich_from_structured(
    contacts: dict, names: list[str], structured: dict, *, region: str | None = None
) -> tuple[dict, list[str], dict]:
    """Fold schema.org/OG data into the page's contacts + names, and return the
    structured 'map' (titles/orgs/locations/social/descriptions) for Page.meta."""
    emails = list(contacts.get("emails") or [])
    phones = list(contacts.get("phones") or [])
    usernames = list(contacts.get("usernames") or [])
    out_names = list(names or [])

    for e in structured.get("emails", []):
        e = e.lower()
        if e not in emails:
            emails.append(e)
    # validate structured telephone strings
    try:
        import phonenumbers

        for raw in structured.get("phones_raw", []):
            for reg in (None, region):
                try:
                    for m in phonenumbers.PhoneNumberMatcher(raw, reg):
                        if phonenumbers.is_valid_number(m.number):
                            e164 = phonenumbers.format_number(m.number, phonenumbers.PhoneNumberFormat.E164)
                            if e164 not in phones:
                                phones.append(e164)
                except Exception:
                    continue
    except Exception:
        pass
    # usernames from sameAs social profile URLs
    for url in structured.get("social", []):
        for u in _SOCIAL_RE.findall(url):
            u = u.strip().lower()
            if u and u not in usernames and u not in _USER_STOP:
                usernames.append(u)
    for n in structured.get("names", []):
        if n not in out_names:
            out_names.append(n)

    meta = {k: structured.get(k, []) for k in ("titles", "orgs", "locations", "social", "descriptions")}
    enriched = {"emails": emails[:50], "phones": phones[:50], "usernames": usernames[:50]}
    return enriched, out_names[:20], meta


def path_allowed(url: str, allowed: list[str], excluded: list[str]) -> bool:
    path = urlsplit(url).path or "/"
    if any(path.startswith(e) for e in excluded if e):
        return False
    if allowed:
        return any(path.startswith(a) for a in allowed)
    return True
