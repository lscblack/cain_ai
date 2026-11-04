"""Post-generation grounding check for the people-analysis output.

Rules (the load-bearing requirement: no invented data passes this check):

* A **heading** is a line whose text, after stripping leading/trailing ``#``,
  ``*``, ``_``, ``:`` and whitespace, equals one of the six section titles
  (case-insensitive). Any other ``#`` line is judged as an ordinary sentence
  and resets the current section to "unknown".
* In the five content sections a sentence is kept only if it **ends** with a
  citation (``[F3]``, ``[F3][F4]`` or ``[F3, F4]``, optionally followed by
  punctuation) and every id cited anywhere in it exists in ``facts``.
* A "<field>: not found" placeholder (in any section) is kept only if it is
  one of the closed gap templates below; a bare "Not found." is regenerated.
* In **Confidence & gaps** a sentence is kept if it is validly cited as above.
  An UNCITED sentence is kept only if, after trimming a leading bullet and the
  trailing full stop and lower-casing, it FULLY matches one of the closed
  ``GAP_TEMPLATES`` (e.g. "No {field} was found.", "{Field} is unconfirmed.",
  "Evidence is limited.", "Sources conflict."), whose only variable slot is a
  field name from the closed ``GAP_FIELDS`` list. Defence in depth: it is
  still dropped if it contains a speculation/sensitive marker (``_SPECULATION``:
  probably, likely, rumour, but, criminal, ethnic, wealth, ...), a digit, more
  than 20 words, or a capitalised word other than the first word (and the
  ID/NID/DB acronyms).
* Cited sentences found before any recognised heading, or under an
  unrecognised heading, are not placed: they go to ``dropped`` prefixed
  ``"[unplaced] "``.
* The output is **rebuilt** in the fixed six-section order; a section with no
  kept lines gets "Not found.".

Limits / residual risk:
* The check verifies that each cited id is well-formed and EXISTS in the
  bundle. It does NOT verify that the fact semantically supports the claim;
  a sentence can still misstate a cited fact.
* Uncited gaps text can only take the fixed template forms, so it cannot
  carry an invented detail; a template can at most state a wrong gap (e.g.
  "No employer was found." when one exists in the bundle).
* A cited sentence anywhere can still attach a valid id to a misstatement
  (semantic misuse of a citation is not detected; see the first point).
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


# Closed list of field names: the ONLY variable slot in a gap template.
GAP_FIELDS = (
    "employer", "occupation", "job title", "phone number", "phone numbers",
    "email address", "email addresses", "address", "location", "date of birth",
    "national id", "nationality", "education", "spouse", "partner", "children",
    "parents", "siblings", "relatives", "associates", "online presence",
    "social media profile", "social media profiles", "photo", "photos",
    "web mention", "web mentions", "organisation", "organisations",
)
_F = "(?:" + "|".join(re.escape(f) for f in sorted(GAP_FIELDS, key=len, reverse=True)) + ")"
# Closed sentence forms, matched against the normalised line (lowercase, single
# spaces, no leading bullet, no trailing full stop). Nothing else uncited is kept.
GAP_TEMPLATES = (
    "no {F} (?:was |were )?found",
    "{F} (?:was |were )?not found",
    "{F}: not found",
    "not found",
    "(?:the )?{F} (?:is|are) unconfirmed",
    "the {F} link is inferred, not confirmed",
    "the {F} is inferred from shared children, not confirmed",
    "web results may refer to a different person with the same name",
    "evidence is limited",
    "evidence is limited to (?:the saved database|web results)",
    "only one source was found",
    "sources conflict",
)
_GAP_RES = tuple(re.compile("^" + t.replace("{F}", _F) + "$") for t in GAP_TEMPLATES)
# Defence in depth: a template line is still dropped if it carries any of these.
_SPECULATION = re.compile(
    r"\b(?:probably|likely|unlikely|possibly|perhaps|appears?|seems?|suggest\w*|impl\w+"
    r"|rumou?rs?|reportedly|allegedly|alleged|describe\w*|claim\w*|whether|but|though"
    r"|although|yet|however|criminal|crime|convict\w*|fraud\w*|smuggl\w*|violen\w*"
    r"|abus\w*|corrupt\w*|ethnic\w*|religio\w*|tribe|race|health|disease|hiv|illness"
    r"|sexual\w*|gay|lesbian|wealth\w*|rich|drug\w*|drunk\w*|drink\w*|hidden)\b",
    re.IGNORECASE,
)
_GAP_MAX_WORDS = 20
_GAP_ACRONYMS = {"ID", "NID", "DB"}  # "national ID" is a listed field


def _normalise_gap(sentence: str) -> str:
    s = _BULLET.sub("", sentence.strip()).strip()
    s = re.sub(r"\s+", " ", s).rstrip(".").strip()
    return s.casefold()


def _allowed_gap(sentence: str) -> bool:
    """An uncited gaps line (or a "<field>: not found" placeholder) is kept only
    if it FULLY matches one of the closed GAP_TEMPLATES and carries no
    speculation marker, digit, extra capitalised word or more than 20 words."""
    if (_SPECULATION.search(sentence) or re.search(r"\d", sentence)
            or len(sentence.split()) > _GAP_MAX_WORDS):
        return False
    words = _WORD.findall(sentence)
    if any(w[0].isupper() and w not in _GAP_ACRONYMS for w in words[1:]):
        return False
    norm = _normalise_gap(sentence)
    return any(r.match(norm) for r in _GAP_RES)


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
            if _allowed_gap(body):
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
            elif section == GAPS and _allowed_gap(sent):
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
