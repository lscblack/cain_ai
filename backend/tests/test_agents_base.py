import dataclasses

import pytest

from app.agents.base import Fact, new_fact_id


def _fact(confidence=50):
    return Fact(id="F1", claim="name", value="x", source="db",
                source_ref="person:1", retrieved_at="2026-11-04T00:00:00Z",
                confidence=confidence)


def test_fact_is_frozen_and_confidence_bounded():
    f = _fact(100)
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.value = "y"
    for bad in (101, -1):
        with pytest.raises(ValueError):
            _fact(bad)
    assert _fact(0).confidence == 0


def test_new_fact_id():
    assert new_fact_id(3) == "F3"
