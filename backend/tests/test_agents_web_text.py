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


def test_bare_spouse_not_a_trigger():
    assert extract_spouse_names("spouse Policy Reform Act") == []
    assert extract_spouse_names("The spouse Health Ministry announced") == []


def test_spouse_of_trigger():
    assert extract_spouse_names("spouse of Alice Mukamana") == ["Alice Mukamana"]


def test_honorific_stripped():
    assert extract_spouse_names("wife of President Jean Paul Nzeyimana") == ["Jean Paul Nzeyimana"]
    assert extract_spouse_names("married to Dr. Marie Uwase") == ["Marie Uwase"]
    assert extract_spouse_names("wife of Dr Kamau") == []


def test_institutions_rejected():
    for t in ("wife of Prime Minister", "married to Kigali City Council", "spouse of Health Ministry"):
        assert extract_spouse_names(t) == []


def test_stops_at_sentence_words_and_caps_tokens():
    assert extract_spouse_names("married to Jean Paul The Minister said") == ["Jean Paul"]
    assert extract_spouse_names("wife of Anna Maria Lucia Rosa Bella Smith") == ["Anna Maria Lucia Rosa"]


def test_newline_separated():
    assert extract_spouse_names("wife of Jean Paul\nNzeyimana Marie") == ["Jean Paul"]
    assert extract_spouse_names("Name: X\nmarried to Marie Uwase\nKigali") == ["Marie Uwase"]


def test_place_names_end_the_name():
    assert extract_spouse_names("married to Jean Paul Kigali Rwanda") == ["Jean Paul"]
    assert extract_spouse_names("wife of Marie Uwase Gasabo") == ["Marie Uwase"]
    assert extract_spouse_names("wife of Kigali Rwanda") == []
