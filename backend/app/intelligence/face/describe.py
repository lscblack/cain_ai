"""Auto-generate a human-readable dossier line for an indexed face.

Composes everything KAI observed about a face on its source page — possible names,
apparent demographics, caption/context, where it was found, and the contact
identifiers co-located on the same page — so a match shows information, not just a
photo. Observations only, never asserted identity.
"""
from __future__ import annotations

import html
from urllib.parse import urlsplit

_SEX = {"M": "male", "F": "female", "m": "male", "f": "female"}


def _clean(s: str | None) -> str:
    return html.unescape(s).strip() if s else ""


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlsplit(url).hostname or "").lstrip("www.") or None
    except Exception:
        return None


def _clean_names(names: list[str], title: str, domain: str | None) -> list[str]:
    """Drop candidates that are really the publication/site name, not a person.

    News crawls often pick the masthead ("The Citizen") out of the title/logo alt.
    A real person's name is >=2 words and isn't contained in the page title or domain.
    """
    tl = (title or "").lower()
    dl = (domain or "").replace(".", " ").lower()
    out: list[str] = []
    for n in names:
        n = _clean(n)
        low = n.lower()
        if not n or len(n) < 3:
            continue
        if len(n.split()) < 2:  # single token — too weak to assert as a person
            continue
        if low in tl or (tl and tl in low):  # same as the masthead
            continue
        if low in dl:  # same as the site name
            continue
        if n not in out:
            out.append(n)
    return out


def face_key_info(extra: dict | None, source_url: str | None) -> dict:
    """Structured, cleaned key info for the UI (entities decoded)."""
    extra = extra or {}
    age = extra.get("age")
    title = _clean(extra.get("page_title"))
    domain = _host(source_url)
    return {
        "names": _clean_names(extra.get("names") or [], title, domain)[:5],
        "page_title": title,
        "caption": _clean(extra.get("caption") or extra.get("alt")),
        "domain": domain,
        "age": age if isinstance(age, int) and age > 0 else None,
        "sex": _SEX.get(extra.get("sex") or ""),
        "emails": extra.get("emails") or [],
        "phones": extra.get("phones") or [],
        "usernames": extra.get("usernames") or [],
        "description": describe_face(extra, source_url),
    }


def describe_face(extra: dict | None, source_url: str | None) -> str:
    extra = extra or {}
    title = _clean(extra.get("page_title"))
    domain = _host(source_url)
    names = _clean_names(extra.get("names") or [], title, domain)[:3]
    caption = _clean(extra.get("caption") or extra.get("alt"))
    age = extra.get("age")
    sex = _SEX.get(extra.get("sex") or "")
    emails = extra.get("emails") or []
    phones = extra.get("phones") or []
    usernames = extra.get("usernames") or []

    titles = [t for t in (extra.get("titles") or []) if t][:2]
    orgs = [o for o in (extra.get("orgs") or []) if o][:2]
    locations = [lc for lc in (extra.get("locations") or []) if lc][:2]

    parts: list[str] = []
    if names:
        parts.append(f"Possible identity: {', '.join(names)}")
    if titles:
        role = ", ".join(titles) + (f" at {', '.join(orgs)}" if orgs else "")
        parts.append(role)
    elif orgs:
        parts.append(f"linked to {', '.join(orgs)}")
    if locations:
        parts.append(f"located in {', '.join(locations)}")
    demo: list[str] = []
    if sex:
        demo.append(sex)
    if isinstance(age, int) and age > 0:
        demo.append(f"~{age} yrs")
    if demo:
        parts.append("appears " + ", ".join(demo))
    if caption:
        parts.append(f'context: "{caption}"')
    loc: list[str] = []
    if title:
        loc.append(f'"{title}"')
    if domain:
        loc.append(domain)
    if loc:
        parts.append("found on " + " — ".join(loc))
    contacts: list[str] = []
    if phones:
        contacts.append(f"{len(phones)} phone{'s' if len(phones) > 1 else ''}")
    if emails:
        contacts.append(f"{len(emails)} email{'s' if len(emails) > 1 else ''}")
    if usernames:
        contacts.append(f"{len(usernames)} handle{'s' if len(usernames) > 1 else ''}")
    if contacts:
        parts.append("linked on the same page: " + ", ".join(contacts))

    if not parts:
        return f"Face observed on {domain or 'a crawled page'}."
    return ". ".join(p[0].upper() + p[1:] for p in parts) + "."
