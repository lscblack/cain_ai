"""Universal query type detection.

Classifies a free-text query into one of the investigation input types so the
UI can route to the right mode. Heuristic/regex based in Phase 3; the phone
module (Phase 4) refines phone parsing with libphonenumber.
"""
from __future__ import annotations

import re
from enum import Enum


class QueryType(str, Enum):
    URL = "url"
    EMAIL = "email"
    PHONE = "phone"
    DOMAIN = "domain"
    USERNAME = "username"
    UNKNOWN = "unknown"


_EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", re.I)
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$", re.I)
_USERNAME_RE = re.compile(r"^@?[a-z0-9][a-z0-9._\-]{1,39}$", re.I)
_PHONE_CHARS_RE = re.compile(r"^[+()\-.\s0-9]+$")


class DetectionResult:
    __slots__ = ("type", "normalized", "original")

    def __init__(self, type_: QueryType, normalized: str, original: str) -> None:
        self.type = type_
        self.normalized = normalized
        self.original = original

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"DetectionResult(type={self.type}, normalized={self.normalized!r})"


def _looks_like_phone(s: str) -> bool:
    if not _PHONE_CHARS_RE.match(s):
        return False
    digits = re.sub(r"\D", "", s)
    return 7 <= len(digits) <= 15


def detect_query_type(query: str) -> DetectionResult:
    q = query.strip()
    if not q:
        return DetectionResult(QueryType.UNKNOWN, "", query)

    lower = q.lower()

    # URL — explicit scheme.
    if lower.startswith(("http://", "https://")):
        return DetectionResult(QueryType.URL, q, query)

    # Email.
    if _EMAIL_RE.match(q):
        return DetectionResult(QueryType.EMAIL, lower, query)

    # Phone — digit-dominant with phone punctuation only.
    if _looks_like_phone(q):
        digits = re.sub(r"[^\d+]", "", q)
        return DetectionResult(QueryType.PHONE, digits, query)

    # Domain — has a dot, valid labels, no '@' or spaces.
    if "@" not in q and " " not in q and _DOMAIN_RE.match(q):
        return DetectionResult(QueryType.DOMAIN, lower, query)

    # Username — handle-like token.
    if _USERNAME_RE.match(q):
        return DetectionResult(QueryType.USERNAME, q.lstrip("@"), query)

    return DetectionResult(QueryType.UNKNOWN, q, query)
