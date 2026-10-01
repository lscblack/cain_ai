"""Evidence-grounded correlation.

Suggests *observed* relationships between entities when they co-occur in the
same source evidence. Suggestions are candidates for the operator to accept;
they are never auto-asserted and never claim the entities are the same person.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from itertools import combinations


@dataclass
class EvidenceRef:
    entity_id: uuid.UUID | None
    source_url: str


@dataclass
class Suggestion:
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    rel_type: str
    source_url: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "source_entity_id": str(self.source_entity_id),
            "target_entity_id": str(self.target_entity_id),
            "rel_type": self.rel_type,
            "source_url": self.source_url,
            "reason": self.reason,
        }


def suggest_relationships(
    evidence: list[EvidenceRef],
    *,
    existing_pairs: set[frozenset[uuid.UUID]] | None = None,
) -> list[Suggestion]:
    """For each source_url, pair every distinct entity observed there.

    existing_pairs: unordered entity-id pairs that already have a relationship,
    so we don't re-suggest them.
    """
    existing_pairs = existing_pairs or set()

    # group entity ids by source url
    by_url: dict[str, set[uuid.UUID]] = {}
    for ev in evidence:
        if ev.entity_id is None or not ev.source_url:
            continue
        by_url.setdefault(ev.source_url, set()).add(ev.entity_id)

    seen: set[tuple[str, frozenset[uuid.UUID]]] = set()
    out: list[Suggestion] = []
    for url, ids in by_url.items():
        if len(ids) < 2:
            continue
        for a, b in combinations(sorted(ids, key=str), 2):
            pair = frozenset({a, b})
            if pair in existing_pairs:
                continue
            dedup_key = (url, pair)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            out.append(
                Suggestion(
                    source_entity_id=a,
                    target_entity_id=b,
                    rel_type="co_observed_on",
                    source_url=url,
                    reason=f"Both entities were observed on {url}",
                )
            )
    return out
