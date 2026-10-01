import pytest

from app.intelligence.detect import QueryType, detect_query_type


@pytest.mark.parametrize(
    "query,expected",
    [
        ("https://example.com/path", QueryType.URL),
        ("http://a.b", QueryType.URL),
        ("alice@example.com", QueryType.EMAIL),
        ("Alice.Smith@Example.COM", QueryType.EMAIL),
        ("+250788123456", QueryType.PHONE),
        ("0788123456", QueryType.PHONE),
        ("(202) 555-0147", QueryType.PHONE),
        ("example.com", QueryType.DOMAIN),
        ("news.example.co.uk", QueryType.DOMAIN),
        ("john_doe", QueryType.USERNAME),
        ("@handle99", QueryType.USERNAME),
        ("", QueryType.UNKNOWN),
        ("a totally random sentence here", QueryType.UNKNOWN),
    ],
)
def test_detect_type(query, expected):
    assert detect_query_type(query).type == expected


def test_phone_normalized_to_digits():
    r = detect_query_type("+250 788 123 456")
    assert r.type == QueryType.PHONE
    assert r.normalized == "+250788123456"


def test_email_lowercased():
    r = detect_query_type("Alice@Example.com")
    assert r.normalized == "alice@example.com"


def test_username_strips_at():
    r = detect_query_type("@osint_guy")
    assert r.type == QueryType.USERNAME
    assert r.normalized == "osint_guy"
