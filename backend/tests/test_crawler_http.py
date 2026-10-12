import time

from app.crawlers import http as H


class _S:
    tor_socks_proxy = ""
    crawl_proxy = ""
    crawl_require_proxy = False
    crawl_rate_delay = 0.0


def _patch(monkeypatch, **kw):
    s = _S()
    for k, v in kw.items():
        setattr(s, k, v)
    monkeypatch.setattr(H, "get_settings", lambda: s)
    return s


def test_proxy_for_onion_and_open_web(monkeypatch):
    _patch(monkeypatch, tor_socks_proxy="socks5://127.0.0.1:9050",
           crawl_proxy="socks5://127.0.0.1:9050")
    assert H._proxy_for("http://abcd.onion/x") == "socks5://127.0.0.1:9050"
    assert H._proxy_for("https://example.com/") == "socks5://127.0.0.1:9050"


def test_proxy_for_direct_when_unset(monkeypatch):
    _patch(monkeypatch)
    assert H._proxy_for("https://example.com/") is None
    assert H._proxy_for("http://abcd.onion/") is None


async def test_require_proxy_blocks_open_web(monkeypatch):
    _patch(monkeypatch, crawl_require_proxy=True)
    monkeypatch.setattr(H, "validate_public_url", lambda u: None)
    r = await H.httpx_fetch("https://example.com/")
    assert r.status == 0  # fail closed: no proxy -> no crawl


async def test_rate_limit_enforces_delay(monkeypatch):
    _patch(monkeypatch, crawl_rate_delay=0.05)
    H._last_hit.pop("h1", None)
    t0 = time.monotonic()
    await H._rate_limit("h1")
    await H._rate_limit("h1")
    assert time.monotonic() - t0 >= 0.05
