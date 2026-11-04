"""Pure text extraction helpers for web-sourced person facts."""
from __future__ import annotations

import re

# Trigger phrase, then a run of words up to punctuation / end of line.
_TRIGGER = re.compile(
    r"\b(?:wife\s+of|husband\s+of|married\s+to|spouse\s+of|spouse\s*:|spouse)\s+"
    r"([^\s.,;:!?()\[\]\"“”]+(?:[ \t]+[^\s.,;:!?()\[\]\"“”]+)*)",
    re.IGNORECASE,
)


def _is_cap(word: str) -> bool:
    """Capitalised (or all-caps) word; accents allowed, e.g. Éric, NZEYIMANA."""
    return word[:1].isupper() and word.replace("-", "").replace("'", "").isalpha()


def extract_spouse_names(text: str) -> list[str]:
    """Return capitalised spouse names (>=2 tokens), deduped, in order."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _TRIGGER.finditer(text or ""):
        tokens: list[str] = []
        for w in m.group(1).split():
            if not _is_cap(w):
                break
            tokens.append(w)
        if len(tokens) < 2:
            continue
        name = " ".join(tokens)
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out
