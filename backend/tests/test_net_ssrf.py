import pytest

from app.core.net import UnsafeUrlError, validate_public_url


def _resolver(mapping):
    """Return a fake resolver mapping host -> list of IP strings."""

    def resolve(host: str) -> list[str]:
        if host not in mapping:
            raise OSError(f"cannot resolve {host}")
        return mapping[host]

    return resolve


def test_public_url_allowed():
    safe = validate_public_url(
        "https://example.com/page", resolver=_resolver({"example.com": ["93.184.216.34"]})
    )
    assert safe.host == "example.com"
    assert safe.scheme == "https"
    assert "93.184.216.34" in safe.resolved_ips


@pytest.mark.parametrize(
    "url,ips",
    [
        ("http://localhost/", {"localhost": ["127.0.0.1"]}),
        ("http://127.0.0.1/", {}),
        ("http://10.0.0.5/", {}),
        ("http://192.168.1.1/", {}),
        ("http://172.16.0.1/", {}),
        ("http://169.254.169.254/latest/meta-data/", {}),
        ("http://[::1]/", {}),
        ("http://[fc00::1]/", {}),
        ("http://metadata.internal/", {"metadata.internal": ["169.254.169.254"]}),
    ],
)
def test_private_and_metadata_blocked(url, ips):
    with pytest.raises(UnsafeUrlError):
        validate_public_url(url, resolver=_resolver(ips))


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x"])
def test_bad_scheme_blocked(url):
    with pytest.raises(UnsafeUrlError):
        validate_public_url(url, resolver=_resolver({"example.com": ["93.184.216.34"]}))


def test_any_private_record_blocks():
    # Host resolves to one public + one private IP -> must be rejected.
    with pytest.raises(UnsafeUrlError):
        validate_public_url(
            "https://sneaky.test/",
            resolver=_resolver({"sneaky.test": ["93.184.216.34", "10.1.2.3"]}),
        )


def test_unresolvable_host_blocked():
    with pytest.raises(UnsafeUrlError):
        validate_public_url("https://nope.invalid/", resolver=_resolver({}))
