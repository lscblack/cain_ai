"""Post-generation grounding check for the people-analysis output.

Rules (the load-bearing requirement: no invented data passes this check):

* A **heading** is a line whose text, after stripping leading/trailing ``#``,
  ``*``, ``_``, ``:`` and whitespace, equals one of the six section titles
  (case-insensitive). Any other ``#`` line is judged as an ordinary sentence
  and resets the current section to "unknown".
* In the five content sections a sentence is kept only if it **ends** with a
  citation (``[F3]``, ``[F3][F4]`` or ``[F3, F4]``, optionally followed by
  punctuation) and every id cited anywhere in it exists in ``facts``.
* A "<label>: not found" placeholder is kept only if it passes the
  no-new-facts filter below; a bare "Not found." is regenerated anyway.
* In **Confidence & gaps** a sentence is kept if it is validly cited as above,
  or if it passes a conservative *no-new-facts* filter: no digits and no
  capitalised word other than the sentence's first word, section-title words
  and a small whitelist (Web, NID, DB, ID, KAI).
* Cited sentences found before any recognised heading, or under an
  unrecognised heading, are not placed: they go to ``dropped`` prefixed
  ``"[unplaced] "``.
* The output is **rebuilt** in the fixed six-section order; a section with no
  kept lines gets "Not found.".

Limits / residual risk:
* The check verifies that each cited id is well-formed and EXISTS in the
  bundle. It does NOT verify that the fact semantically supports the claim;
  a sentence can still misstate a cited fact.
* The no-new-facts filter is lexical. An uncited gaps sentence can still
  carry an invented detail in lowercase words or in its first word
  (e.g. "Kigali records are thin."). It cannot carry digits or other
  proper nouns.
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
GAPS = "Confidence & gaps"
NOT_FOUND = "Not found."
_BY_KEY = {s.casefold(): s for s in SECTIONS}

_CITE_GROUP = re.compile(r"\[(F\d+(?:\s*[,;]\s*F\d+)*)\]")
_CITE_ID = re.compile(r"F\d+")
_TRAILING_CITE = re.compile(r"(?:\[F\d+(?:\s*[,;]\s*F\d+)*\]\s*)+[.!?;:,]*\s*$")
# Split after sentence-final punctuation; a citation right after the full stop
# stays with its sentence. No split after "]": a mid-sentence citation must not
# become a sentence end.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[^\s\[])")
_ABBREV_END = re.compile(r"\b(?:Dr|Mr|Mrs|Ms|St|Prof|No)\.$")
_BULLET = re.compile(r"^(\s*(?:[-*•]|\d+[.)])\s+)")
_BARE_NOT_FOUND = re.compile(r"^not found\.?$", re.IGNORECASE)
_LABEL_NOT_FOUND = re.compile(r"^[^:]{1,60}:\s*not found\.?$", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_ALLOWED_CAPS = {w for s in SECTIONS for w in _WORD.findall(s)} | {
    w.capitalize() for s in SECTIONS for w in _WORD.findall(s)
} | {"Web", "NID", "DB", "ID", "KAI"}


@dataclass
class GroundResult:
    text: str
    dropped: list[str] = field(default_factory=list)
    kept: int = 0  # verified cited sentences placed under a recognised section


def _heading(line: str) -> str | None:
    """Canonical section title if ``line`` is one of the six headings, else None."""
    return _BY_KEY.get(line.strip().strip("#*_: \t").casefold())


def _sentences(body: str) -> list[str]:
    out: list[str] = []
    for part in (p.strip() for p in _SENT_SPLIT.split(body)):
        if not part:
            continue
        if out and _ABBREV_END.search(out[-1]):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def _validly_cited(sentence: str, known: set[str]) -> bool:
    if not _TRAILING_CITE.search(sentence):
        return False
    ids = [i for g in _CITE_GROUP.findall(sentence) for i in _CITE_ID.findall(g)]
    return bool(ids) and all(i in known for i in ids)


def _no_new_facts(sentence: str) -> bool:
    if re.search(r"\d", sentence):
        return False
    words = _WORD.findall(sentence)
    return all(not w[0].isupper() or w in _ALLOWED_CAPS for w in words[1:])


def ground_detail(text: str, facts: list[Fact]) -> GroundResult:
    known = {f.id for f in facts if f.id}
    placed: dict[str, list[str]] = {s: [] for s in SECTIONS}
    dropped: list[str] = []
    kept = 0
    section: str | None = None  # None = before any heading / unknown heading

    for line in (text or "").splitlines():
        if not line.strip():
            continue
        title = _heading(line)
        if title is not None:
            section = title
            continue
        if line.lstrip().startswith("#"):  # unrecognised heading: judge as a sentence
            section = None
            line = line.lstrip().lstrip("#")

        m = _BULLET.match(line)
        prefix = m.group(1).lstrip() if m else ""
        body = line[len(m.group(1)):].strip() if m else line.strip()
        if not body:
            continue
        if _BARE_NOT_FOUND.match(body):
            continue  # regenerated for empty sections
        if section is not None and _LABEL_NOT_FOUND.match(body):
            if _no_new_facts(body):
                placed[section].append(prefix + body)
            else:
                dropped.append(body)
            continue

        good: list[str] = []
        for sent in _sentences(body):
            if _validly_cited(sent, known):
                if section is None:
                    dropped.append(f"[unplaced] {sent}")
                else:
                    good.append(sent)
                    kept += 1
            elif section == GAPS and _no_new_facts(sent):
                good.append(sent)
            else:
                dropped.append(sent)
        if good:
            placed[section].append(prefix + " ".join(good))  # type: ignore[index]

    blocks = [f"## {s}\n" + "\n".join(placed[s] or [NOT_FOUND]) for s in SECTIONS]
    return GroundResult(text="\n\n".join(blocks), dropped=dropped, kept=kept)


def ground(text: str, facts: list[Fact]) -> tuple[str, list[str]]:
    """Return (rebuilt kept text, dropped sentences)."""
    r = ground_detail(text, facts)
    return r.text, r.dropped
