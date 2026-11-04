"""Post-generation grounding check for the people-analysis output.

A sentence survives only if it cites at least one fact (``[F3]`` or
``[F3, F4]``) and every id it cites exists in the evidence bundle. Headings,
blank lines, bare "not found" placeholders and everything inside the
"Confidence & gaps" section are exempt (kept as written).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agents.base import Fact

SECTIONS = (
    "Identity",
    "Location",
    "Family & associates",
    "Occupation & activity",
    "Online presence",
    "Confidence & gaps",
)
GAPS_SECTION = "confidence & gaps"
_SECTION_KEYS = {s.casefold() for s in SECTIONS}

_CITE_GROUP = re.compile(r"\[(F\d+(?:\s*[,;]\s*F\d+)*)\]")
_CITE_ID = re.compile(r"F\d+")
# Split after sentence-final punctuation (citations directly after the full
# stop stay with their sentence), or after a citation that ends a sentence
# without punctuation and is followed by a new capitalised sentence.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[^\s\[])|(?<=\])\s+(?=[A-Z])")
_BULLET = re.compile(r"^(\s*(?:[-*•]|\d+[.)])\s+)")
_NOT_FOUND = re.compile(r"^(?:[A-Za-z][\w &/'-]{0,60}:\s*)?not found\.?$", re.IGNORECASE)


@dataclass
class GroundResult:
    text: str
    dropped: list[str] = field(default_factory=list)
    kept: int = 0  # cited, verified sentences kept outside exempt areas


def _heading_key(line: str) -> str | None:
    """Return the normalised heading text if ``line`` is a heading, else None."""
    s = line.strip()
    if s.startswith("#"):
        return s.lstrip("#").strip().strip("*_: ").casefold()
    bare = s.strip("*_").strip().rstrip(":").strip().strip("*_").casefold()
    return bare if bare in _SECTION_KEYS else None


def _cited_ids(sentence: str) -> list[str]:
    ids: list[str] = []
    for group in _CITE_GROUP.findall(sentence):
        ids.extend(_CITE_ID.findall(group))
    return ids


def ground_detail(text: str, facts: list[Fact]) -> GroundResult:
    known = {f.id for f in facts if f.id}
    out: list[str] = []
    dropped: list[str] = []
    kept = 0
    in_gaps = False

    for line in (text or "").splitlines():
        if not line.strip():
            out.append(line)
            continue
        key = _heading_key(line)
        if key is not None:
            in_gaps = key == GAPS_SECTION
            out.append(line)
            continue
        if in_gaps:
            out.append(line)
            continue

        m = _BULLET.match(line)
        prefix = m.group(1) if m else ""
        body = line[len(prefix):].strip()
        if _NOT_FOUND.match(body):
            out.append(line)
            continue

        good: list[str] = []
        for sent in (p.strip() for p in _SENT_SPLIT.split(body)):
            if not sent:
                continue
            ids = _cited_ids(sent)
            if ids and all(i in known for i in ids):
                good.append(sent)
            else:
                dropped.append(sent)
        if good:
            kept += len(good)
            out.append(prefix + " ".join(good))

    return GroundResult(text="\n".join(out).strip("\n"), dropped=dropped, kept=kept)


def ground(text: str, facts: list[Fact]) -> tuple[str, list[str]]:
    """Return (kept text, dropped sentences)."""
    r = ground_detail(text, facts)
    return r.text, r.dropped
