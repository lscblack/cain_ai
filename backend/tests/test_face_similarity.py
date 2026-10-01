from app.database.entities import ConfidenceBand
from app.intelligence.face.similarity import (
    band_for_similarity,
    cosine_similarity,
    is_match,
)


def test_cosine_identical():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_cosine_orthogonal():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_mismatched_or_empty():
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0


def test_bands():
    assert band_for_similarity(0.9) == ConfidenceBand.POTENTIAL_MATCH
    assert band_for_similarity(0.45) == ConfidenceBand.STRONG
    assert band_for_similarity(0.3) == ConfidenceBand.POSSIBLE
    assert band_for_similarity(0.1) is None


def test_is_match_floor():
    assert is_match(0.28) is True
    assert is_match(0.27) is False
