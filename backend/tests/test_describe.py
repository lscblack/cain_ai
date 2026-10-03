"""Auto-generated face description composer."""
from app.intelligence.face.describe import describe_face, face_key_info


def test_describe_composes_key_info():
    d = describe_face(
        {"age": 36, "sex": "F", "names": ["Ange Eric Hatangimana"],
         "page_title": "UMUSEKE &#8211; Amakuru", "phones": ["+250788111222"],
         "usernames": ["umuseke"]},
        "https://umuseke.rw/2026/10/slug",
    )
    assert "Ange Eric Hatangimana" in d
    assert "female" in d and "36" in d
    assert "umuseke.rw" in d
    assert "–" in d  # HTML entity decoded in title
    assert "1 phone" in d and "1 handle" in d


def test_describe_filters_publication_name():
    # masthead that equals the title is not a person
    d = describe_face({"names": ["The Citizen"], "page_title": "The Citizen"},
                      "https://thecitizen.co.tz/x")
    assert "Possible identity" not in d
    assert "thecitizen.co.tz" in d


def test_describe_empty_is_graceful():
    # domain only -> "Found on <domain>."
    assert describe_face({}, "https://diggers.news/x") == "Found on diggers.news."
    # nothing at all -> generic fallback
    assert describe_face({}, None) == "Face observed on a crawled page."


def test_key_info_cleans_names():
    info = face_key_info(
        {"names": ["The Citizen", "Jane Doe"], "page_title": "The Citizen"},
        "https://thecitizen.co.tz/x",
    )
    assert info["names"] == ["Jane Doe"]
    assert info["domain"] == "thecitizen.co.tz"
