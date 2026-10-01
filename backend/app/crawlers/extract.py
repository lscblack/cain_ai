"""HTML extraction: image URLs and same-scope links. Pure, no network."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

_IMG_RE = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
_SRCSET_RE = re.compile(r"<img\b[^>]*?\bsrcset\s*=\s*[\"']([^\"']+)[\"']", re.I)
_HREF_RE = re.compile(r"<a\b[^>]*?\bhref\s*=\s*[\"']([^\"']+)[\"']", re.I)

_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def extract_image_urls(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    for m in _IMG_RE.findall(html or ""):
        urls.append(urljoin(base_url, m.strip()))
    for srcset in _SRCSET_RE.findall(html or ""):
        for part in srcset.split(","):
            candidate = part.strip().split(" ")[0]
            if candidate:
                urls.append(urljoin(base_url, candidate))
    # dedup, keep plausible images only
    seen: list[str] = []
    for u in urls:
        path = urlsplit(u).path.lower()
        if u not in seen and (path.endswith(_IMG_EXT) or "image" in path):
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
