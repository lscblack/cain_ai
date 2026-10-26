"""web.search / web.fetch: open-internet + Tor hidden-service (.onion) research,
read-only, SSRF-guarded. No real network — the HTTP layer is monkeypatched."""
from __future__ import annotations

import pytest

from app.security import adapters, registry
from app.security import service as service_mod
from app.crawlers.runner import Fetched


def test_web_tool_is_registered_passive_builtin():
    tool, op = registry.get_operation("web.search")
    assert tool.source == "builtin" and op.posture == registry.PASSIVE
    tool2, op2 = registry.get_operation("web.fetch")
    assert tool2.source == "builtin" and op2.posture == registry.PASSIVE
    # builtin tools are always "installed" — nothing to apt-install for this one
    assert (pytest := None) or True


async def test_builtin_web_tools_are_always_installed():
    tool, _ = registry.get_operation("web.search")
    disc = await registry.discover(tool)
    assert disc.installed is True


# ───────────────────────── web.search ──────────────────────────────────── #

async def test_web_search_returns_candidates_with_provenance(monkeypatch):
    async def fake(queries, **kw):
        assert queries == ["ransomware group X"]
        return {"example.com": "https://example.com/", "other.org": "https://other.org/"}

    monkeypatch.setattr("app.discovery.search.search_candidates_free", fake)
    out = await adapters.web_search({"query": "ransomware group X"})
    assert out["count"] == 2
    assert {"domain": "example.com", "url": "https://example.com/"} in out["results"]


async def test_web_search_requires_a_query():
    with pytest.raises(ValueError):
        await adapters.web_search({})


# ───────────────────────── web.fetch ───────────────────────────────────── #

async def test_web_fetch_reads_page_text(monkeypatch):
    html = b"<html><head><title>Example Domain</title></head><body><p>Hello world</p></body></html>"

    async def fake_fetch(url):
        assert url == "https://example.com/"
        return Fetched(status=200, content_type="text/html; charset=utf-8", body=html)

    monkeypatch.setattr("app.crawlers.http.httpx_fetch", fake_fetch)
    out = await adapters.web_fetch({"url": "https://example.com/"})
    assert out["ok"] is True and out["status"] == 200
    assert out["title"] == "Example Domain"
    assert "Hello world" in out["text"]


async def test_web_fetch_refuses_a_private_target():
    with pytest.raises(ValueError, match="refused"):
        await adapters.web_fetch({"url": "http://127.0.0.1:8001/admin"})


async def test_web_fetch_a_reachable_onion_address(monkeypatch):
    """.onion is never DNS/IP-checked (it has no IP) — it's reached only via the
    Tor SOCKS proxy, which app.crawlers.http routes to automatically."""
    html = b"<html><head><title>Hidden</title></head><body>secret page</body></html>"

    async def fake_fetch(url):
        assert url.endswith(".onion/")
        return Fetched(status=200, content_type="text/html", body=html)

    monkeypatch.setattr("app.crawlers.http.httpx_fetch", fake_fetch)
    out = await adapters.web_fetch({"url": "http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/"})
    assert out["ok"] is True and out["title"] == "Hidden"


async def test_web_fetch_onion_without_tor_reports_a_clear_reason(monkeypatch):
    async def fake_fetch(url):
        return Fetched(status=0)  # app.crawlers.http fails closed with no Tor proxy

    monkeypatch.setattr("app.crawlers.http.httpx_fetch", fake_fetch)
    out = await adapters.web_fetch({"url": "http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/"})
    assert out["ok"] is False and "Tor" in out["error"]


async def test_web_fetch_non_text_content_is_not_extracted(monkeypatch):
    async def fake_fetch(url):
        return Fetched(status=200, content_type="image/png", body=b"\x89PNG...")

    monkeypatch.setattr("app.crawlers.http.httpx_fetch", fake_fetch)
    out = await adapters.web_fetch({"url": "https://example.com/logo.png"})
    assert out["ok"] is True and "text" not in out and out["content_type"] == "image/png"


async def test_web_fetch_non_200_is_reported_honestly(monkeypatch):
    async def fake_fetch(url):
        return Fetched(status=404, content_type="text/html")

    monkeypatch.setattr("app.crawlers.http.httpx_fetch", fake_fetch)
    out = await adapters.web_fetch({"url": "https://example.com/gone"})
    assert out["ok"] is False and out["status"] == 404


# ───────────────────────── through the service layer ───────────────────── #

async def test_web_fetch_runs_end_to_end_through_run_operation(monkeypatch, db_session):
    async def fake_fetch(url):
        return Fetched(status=200, content_type="text/html",
                       body=b"<title>T</title><body>hi</body>")

    monkeypatch.setattr("app.crawlers.http.httpx_fetch", fake_fetch)
    import uuid
    out = await service_mod.run_operation(
        db_session, user_id=uuid.uuid4(), op_key="web.fetch", params={"url": "https://example.com/"},
    )
    assert out["ok"] is True and out["result"]["title"] == "T"
