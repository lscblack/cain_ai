from app.agents.web_text import extract_spouse_names


def test_wife_of():
    assert extract_spouse_names("She is the wife of Jean Paul Nzeyimana.") == ["Jean Paul Nzeyimana"]


def test_married_to_stops_at_lowercase():
    assert extract_spouse_names("married to Marie Uwase and living in Kigali") == ["Marie Uwase"]


def test_none():
    assert extract_spouse_names("no family mentioned") == []


def test_single_token_rejected():
    assert extract_spouse_names("wife of John") == []


def test_accented_name():
    assert extract_spouse_names("wife of Éric Ndayisaba") == ["Éric Ndayisaba"]


def test_allcaps_and_husband_spouse():
    assert extract_spouse_names("Husband of NZEYIMANA Jean.") == ["NZEYIMANA Jean"]
    assert extract_spouse_names("Spouse: Alice Mukamana") == ["Alice Mukamana"]


def test_dedupe_preserves_order():
    t = "wife of Marie Uwase. Later, married to Marie Uwase; husband of Anne Kamau."
    assert extract_spouse_names(t) == ["Marie Uwase", "Anne Kamau"]
