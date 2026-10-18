"""Redact secrets from tool output and anything headed to the model/logs."""
from __future__ import annotations

import re

from app.core.config import get_settings

_PLACEHOLDER = "«redacted»"


def _secret_values() -> list[str]:
    s = get_settings()
    candidates = [
        s.app_secret_key,
        s.admin_password,
        s.openrouter_api_key,
        s.openai_api_key,
        s.serpapi_api_key,
        s.tomtom_api_key,
        s.cesium_ion_token,
        s.firms_map_key,
        s.aisstream_api_key,
        s.opensky_client_secret,
        s.windy_webcams_api_key,
    ]
    # DB password from the URL
    m = re.search(r"://[^:]+:([^@]+)@", s.database_url)
    if m:
        candidates.append(m.group(1))
    return [c for c in candidates if c and len(c) >= 6 and c != "change-me"]


# Generic high-entropy / known-token patterns.
_PATTERNS = [
    re.compile(r"(?i)\b(authorization|bearer|api[-_]?key|token|password|secret)\b\s*[:=]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]


def redact(text: str) -> str:
    if not text:
        return text
    for secret in _secret_values():
        text = text.replace(secret, _PLACEHOLDER)
    for pat in _PATTERNS:
        text = pat.sub(_PLACEHOLDER, text)
    return text
