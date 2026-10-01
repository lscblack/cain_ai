from app.intelligence.phone.normalize import analyze_phone


def test_valid_e164_rwanda():
    r = analyze_phone("+250788123456")
    assert r.parsed is True
    assert r.valid is True
    assert r.e164 == "+250788123456"
    assert r.country_code == 250
    assert r.region == "RW"
    assert "250788123456" in r.variants
    assert "0788123456" in r.variants


def test_us_number_with_region():
    r = analyze_phone("(202) 555-0147", default_region="US")
    assert r.parsed is True
    assert r.country_code == 1
    assert r.region == "US"
    assert r.e164 == "+12025550147"


def test_national_number_needs_region():
    # Without a region a bare national number cannot be parsed.
    r = analyze_phone("0788123456")
    assert r.parsed is False
    assert r.error is not None


def test_national_number_with_region():
    r = analyze_phone("0788123456", default_region="RW")
    assert r.parsed is True
    assert r.e164 == "+250788123456"


def test_garbage_input():
    r = analyze_phone("not a phone")
    assert r.parsed is False
    assert r.error is not None


def test_empty_input():
    r = analyze_phone("")
    assert r.parsed is False
    assert r.error == "empty"
