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


def path_allowed(url: str, allowed: list[str], excluded: list[str]) -> bool:
    path = urlsplit(url).path or "/"
    if any(path.startswith(e) for e in excluded if e):
        return False
    if allowed:
        return any(path.startswith(a) for a in allowed)
    return True
