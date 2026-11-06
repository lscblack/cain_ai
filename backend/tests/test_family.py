from app.database.models.enrich import Person
from app.enrich.family import same_name, sibling_score, parent_score, name_tokens


def P(nid, **kw):
    return Person(nid=nid, raw={}, **kw)


LOC = dict(district="Gasabo", cell="Kimironko", village="Amahoro")


def test_name_matching_is_order_and_accent_insensitive():
    assert same_name("Jean Paul NZEYIMANA", "NZEYIMANA jean paul")
    assert name_tokens("Éric") == name_tokens("ERIC")
    assert not same_name("NZEYIMANA", "NZEYIMANA")  # single token = too generic


def test_both_parents_and_same_place_is_100():
    a = P("1", father_names="JEAN NZEYIMANA", mother_names="MARIE UWASE", **LOC)
    b = P("2", father_names="NZEYIMANA JEAN", mother_names="UWASE MARIE", **LOC)
    assert sibling_score(a, b)[:2] == (100, "sibling")


def test_both_parents_other_place_is_90():
    a = P("1", father_names="JEAN NZEYIMANA", mother_names="MARIE UWASE", **LOC)
    b = P("2", father_names="JEAN NZEYIMANA", mother_names="MARIE UWASE", district="Huye")
    assert sibling_score(a, b)[0] == 90


def test_one_parent_scores_lower():
    a = P("1", father_names="JEAN NZEYIMANA", mother_names="MARIE UWASE", **LOC)
    half = P("2", father_names="JEAN NZEYIMANA", mother_names="ROSE MUKAMANA", district="Huye")
    assert sibling_score(a, half)[0] == 55
    near = P("3", father_names="JEAN NZEYIMANA", mother_names="ROSE MUKAMANA", **LOC)
    assert sibling_score(a, near)[0] == 75


def test_unrelated_and_self_are_not_siblings():
    a = P("1", father_names="JEAN NZEYIMANA", **LOC)
    assert sibling_score(a, P("2", father_names="PETER HABYARIMANA", **LOC)) is None
    assert sibling_score(a, a) is None


def test_parent_sex_and_age_gap():
    child = P("1", date_of_birth="01/01/2000", district="Gasabo")
    dad = P("2", sex="M", date_of_birth="1970", district="Gasabo")
    assert parent_score(child, dad, "father")[0] >= 90
    assert parent_score(child, dad, "mother") is None            # wrong sex
    assert parent_score(child, P("3", sex="M", date_of_birth="1995"), "father") is None  # 5y gap


from app.enrich.family import simplify, kin_label


def test_kinship_paths_simplify():
    assert simplify(("up", "down")) == ("side",)                      # parent's child = sibling
    assert simplify(("up", "up", "down")) == ("up", "side")           # grandparent's child = uncle/aunt
    assert simplify(("up", "up", "down", "down")) == ("up", "side", "down")  # = cousin
    assert simplify(("side", "up")) == ("up",)                        # sibling's parent = parent
    assert simplify(("side", "side")) == ("side",)
    assert simplify(("up", "side", "up")) == ("up", "up")             # parent's sibling's parent = grandparent


def test_kinship_labels_by_sex():
    assert kin_label(("up", "side"), "M") == "uncle"
    assert kin_label(("up", "side"), "F") == "aunt"
    assert kin_label(("up", "side", "down"), None) == "cousin"
    assert kin_label(("side", "down"), "F") == "niece"
    assert kin_label(("up", "up"), "Male") == "grandfather"
    assert kin_label(("up", "up", "up", "up"), None).startswith("relative")


def test_name_order_spacing_and_case_never_matter():
    from itertools import permutations
    base = ["Adelle", "Marie", "IRIBAGIZA"]
    variants = [" ".join(p) for p in permutations(base)] + ["  iribagiza   ADELLE marie "]
    assert all(same_name("Adelle Marie IRIBAGIZA", v) for v in variants)
    a = P("1", father_names="Evariste MURANGIRA", mother_names="Adelle Marie IRIBAGIZA", **LOC)
    for v in variants:
        b = P("2", father_names="MURANGIRA Evariste", mother_names=v, **LOC)
        assert sibling_score(a, b)[0] == 100
