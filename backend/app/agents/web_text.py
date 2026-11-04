"""Pure text extraction helpers for web-sourced person facts."""
from __future__ import annotations

import re

# Trigger phrase, then a run of words up to punctuation / end of line.
_TRIGGER = re.compile(
    r"\b(?:wife\s+of|husband\s+of|married\s+to|spouse\s+of|spouse\s*:)\s+"
    r"([^\s.,;:!?()\[\]\"“”]+(?:[ \t]+[^\s.,;:!?()\[\]\"“”]+)*)",
    re.IGNORECASE,
)


_HONORIFICS = {"president", "dr", "mr", "mrs", "ms", "hon", "prof", "minister", "madam"}
_INSTITUTIONS = {
    "ministry", "council", "minister", "city", "prime", "government", "ltd",
    "company", "bank", "university", "authority", "commission", "committee",
    "district", "republic",
}
_STOP = {"the", "a", "an", "in", "at", "on", "of", "and", "for", "to", "by", "with"}
_DOTTED_TITLE = re.compile(r"\b(Dr|Mr|Mrs|Ms|Hon|Prof)\.(?=\s)")
_MAX_TOKENS = 4


def _is_cap(word: str) -> bool:
    """Capitalised (or all-caps) word; accents allowed, e.g. Éric, NZEYIMANA."""
    return word[:1].isupper() and word.replace("-", "").replace("'", "").isalpha()


def extract_spouse_names(text: str) -> list[str]:
    """Return capitalised spouse names (>=2 tokens), deduped, in order."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _TRIGGER.finditer(_DOTTED_TITLE.sub(r"\1", text or "")):
        tokens: list[str] = []
        for w in m.group(1).split():
            if not _is_cap(w) or w.casefold() in _STOP:
                break
            if not tokens and w.casefold() in _HONORIFICS:
                continue
            tokens.append(w)
            if len(tokens) == _MAX_TOKENS:
                break
        if len(tokens) < 2 or any(t.casefold() in _INSTITUTIONS for t in tokens):
            continue
        name = " ".join(tokens)
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out
