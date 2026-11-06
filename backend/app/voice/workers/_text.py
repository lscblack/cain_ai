"""Splits long text into chunks a TTS model can synthesize well. Standard library only."""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

_SENTENCE_END = re.compile(r"(?<=[.!?…。！？；;])[\"'”’)\]]*\s+|(?<=[。！？；])")
_CLAUSE_END = re.compile(r"(?<=[,:，：、—])\s*")


@dataclass(frozen=True)
class Chunk:
    text: str
    # Silence to leave after this chunk, so joins follow the structure of the text.
    pause: str  # "none" | "sentence" | "paragraph"


def _split_oversized(sentence: str, limit: int) -> list[str]:
    """Break one too-long sentence at clause marks, then at spaces, then hard."""
    parts: list[str] = []
    current = ""
    for piece in _CLAUSE_END.split(sentence):
        while len(piece) > limit:
            cut = piece.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            head, piece = piece[:cut], piece[cut:].lstrip()
            if current:
                parts.append(current)
                current = ""
            parts.append(head)
        if current and len(current) + len(piece) + 1 > limit:
            parts.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip() if current else piece
    if current:
        parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, limit: int = 300) -> list[Chunk]:
    """Group sentences up to ``limit`` characters, never crossing a paragraph."""
    chunks: list[Chunk] = []
    for paragraph in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if not paragraph:
            continue
        pieces: list[str] = []
        current = ""
        for sentence in (s.strip() for s in _SENTENCE_END.split(paragraph)):
            if not sentence:
                continue
            for part in ([sentence] if len(sentence) <= limit else _split_oversized(sentence, limit)):
                if current and len(current) + len(part) + 1 > limit:
                    pieces.append(current)
                    current = part
                else:
                    current = f"{current} {part}".strip() if current else part
        if current:
            pieces.append(current)
        chunks.extend(Chunk(p, "sentence") for p in pieces)
        if chunks:
            chunks[-1] = Chunk(chunks[-1].text, "paragraph")
    if chunks:
        chunks[-1] = Chunk(chunks[-1].text, "none")
    return chunks


def _word_key(word: str) -> str:
    return re.sub(r"[^\w]", "", word).lower()


def reconcile_transcript(given: str, heard: str) -> str:
    """The transcript the model gets must say exactly what its audio says.

    If it says more, the model treats the rest as unfinished and reads it aloud before the
    requested text. Keeps the operator's own wording, which beats a machine transcript, up to
    where the audio really ends; uses the machine transcript if theirs is not of this audio.
    """
    given, heard = given.strip(), heard.strip()
    if not given:
        return heard
    if not heard:
        return given
    given_words, heard_words = given.split(), heard.split()
    blocks = SequenceMatcher(
        None, [_word_key(w) for w in given_words], [_word_key(w) for w in heard_words], autojunk=False,
    ).get_matching_blocks()
    matched = sum(b.size for b in blocks)
    if matched < len(heard_words) * 0.5:
        return heard
    end = max((b.a + b.size for b in blocks if b.size >= 2), default=0)
    if end == 0:
        return heard
    # A few unmatched last words are transcription noise rather than speech that isn't there.
    if len(given_words) - end <= max(3, len(given_words) // 20):
        return given
    return " ".join(given_words[:end])


def max_speech_seconds(text: str) -> float:
    """Longer than any natural reading of this text, so a runaway generation has a limit."""
    wide = sum(1 for c in text if ord(c) >= 0x2E80)
    return max(6.0, (len(text) - wide) / 6.0 + wide / 2.0)
