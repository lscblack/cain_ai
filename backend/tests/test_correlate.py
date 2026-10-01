import uuid

from app.intelligence.correlation.correlate import (
    EvidenceRef,
    Suggestion,
    suggest_relationships,
)


def test_co_occurrence_suggested():
    e1, e2 = uuid.uuid4(), uuid.uuid4()
    url = "https://example.com/page"
    suggestions = suggest_relationships(
        [EvidenceRef(e1, url), EvidenceRef(e2, url)]
    )
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.rel_type == "co_observed_on"
    assert s.source_url == url
    assert {s.source_entity_id, s.target_entity_id} == {e1, e2}


def test_no_suggestion_for_single_entity_on_url():
    e1 = uuid.uuid4()
    assert suggest_relationships([EvidenceRef(e1, "https://x.com")]) == []


def test_evidence_without_entity_ignored():
    e1 = uuid.uuid4()
    out = suggest_relationships(
        [EvidenceRef(e1, "https://x.com"), EvidenceRef(None, "https://x.com")]
    )
    assert out == []


def test_existing_pair_not_resuggested():
    e1, e2 = uuid.uuid4(), uuid.uuid4()
    url = "https://example.com"
    existing = {frozenset({e1, e2})}
    out = suggest_relationships(
        [EvidenceRef(e1, url), EvidenceRef(e2, url)], existing_pairs=existing
    )
    assert out == []


def test_three_entities_make_three_pairs():
    ids = [uuid.uuid4() for _ in range(3)]
    url = "https://example.com"
    out = suggest_relationships([EvidenceRef(i, url) for i in ids])
    assert len(out) == 3


def test_suggestion_to_dict():
    e1, e2 = uuid.uuid4(), uuid.uuid4()
    s = Suggestion(e1, e2, "co_observed_on", "https://x.com", "reason")
    d = s.to_dict()
    assert d["rel_type"] == "co_observed_on"
    assert isinstance(d["source_entity_id"], str)
