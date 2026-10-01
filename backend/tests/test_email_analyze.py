from app.intelligence.email.analyze import analyze_email


def _resolver(mapping):
    def resolve(name, rtype):
        key = (name.lower(), rtype)
        if key not in mapping:
            raise LookupError(f"no {rtype} for {name}")
        return mapping[key]

    return resolve


def test_invalid_format():
    r = analyze_email("not-an-email")
    assert r.valid_format is False
    assert "invalid_email_format" in r.notes


def test_valid_split_and_gravatar_and_usernames():
    r = analyze_email("John.Doe99@Example.com")
    assert r.valid_format is True
    assert r.local == "john.doe99"
    assert r.domain == "example.com"
    assert r.gravatar_url.startswith("https://www.gravatar.com/avatar/")
    # derived usernames: full, parts, digit-stripped
    assert "john" in r.derived_usernames
    assert "doe99" in r.derived_usernames
    assert "john.doe99" in r.derived_usernames


def test_dns_not_checked_without_resolver():
    r = analyze_email("a@example.com")
    assert r.dns_checked is False
    assert "dns_not_checked" in r.notes
    assert r.has_mx is None


def test_dns_records_found():
    res = _resolver(
        {
            ("example.com", "MX"): ["mail.example.com"],
            ("example.com", "TXT"): ["v=spf1 include:_spf.example.com ~all", "other=1"],
            ("_dmarc.example.com", "TXT"): ["v=DMARC1; p=reject"],
        }
    )
    r = analyze_email("a@example.com", dns_resolver=res)
    assert r.dns_checked is True
    assert r.has_mx is True
    assert r.mx_records == ["mail.example.com"]
    assert r.spf.startswith("v=spf1")
    assert r.dmarc.startswith("v=DMARC1")


def test_dns_no_records():
    res = _resolver({})
    r = analyze_email("a@nodns.test", dns_resolver=res)
    assert r.dns_checked is True
    assert r.has_mx is False
    assert r.mx_records == []
    assert r.spf is None
    assert r.dmarc is None
