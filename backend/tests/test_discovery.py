"""Offline tests for the Source Discovery Engine (no network, no SerpAPI)."""
from __future__ import annotations

import pytest

from app.crawlers.runner import Fetched
from app.discovery import queries as q
from app.discovery import search as s
from app.discovery.engine import term_queries
from app.discovery.evaluate import evaluate_domain


def test_generate_queries_uses_country_and_tld():
    out = q.generate_queries("rwanda", ["phone"], ["phone"])
    assert any("Rwanda" in x for x in out)
    assert any(x.startswith("site:.rw") for x in out)
    assert len(out) == len(set(out))  # deduped


def test_generate_queries_defaults_when_empty():
    out = q.generate_queries("", [], [])
    assert out  # falls back to default categories/targets


def test_generate_queries_multi_covers_all_countries():
    out = q.generate_queries_multi(["rwanda", "kenya"], ["people"], ["phone"])
    assert any("Rwanda" in x for x in out)
    assert any("Kenya" in x for x in out)
    assert len(out) == len(set(out))  # deduped across countries


def test_generate_queries_multi_defaults_empty():
    assert q.generate_queries_multi([], ["people"], ["phone"])  # falls back to rwanda


def test_discovery_run_in_resolved_countries():
    from app.api.discovery import DiscoveryRunIn

    assert DiscoveryRunIn(countries=["kenya", "uganda"]).resolved_countries() == ["kenya", "uganda"]
    assert DiscoveryRunIn(country="ghana").resolved_countries() == ["ghana"]  # back-compat
    assert DiscoveryRunIn().resolved_countries() == ["rwanda"]  # default


def test_expand_query_tips():
    from app.discovery.engine import expand_query_tips

    out = expand_query_tips(
        ['"{name}" journalist', "site:x.com {name}", "literal query", "  "],
        ["John Doe", "Jane Roe"],
    )
    assert '"John Doe" journalist' in out
    assert '"Jane Roe" journalist' in out
    assert "site:x.com John Doe" in out
    assert "literal query" in out  # no {name} -> run as-is
    assert out == list(dict.fromkeys(out))  # deduped, order preserved


def test_name_deep_queries_covers_key_sources():
    from app.discovery.queries import name_deep_queries

    out = name_deep_queries(["Jane Doe"])
    assert '"Jane Doe" site:en.wikipedia.org' in out
    assert '"Jane Doe" site:github.com' in out
    assert '"Jane Doe" site:linkedin.com/in' in out
    assert any("portfolio" in q for q in out)
    assert len(out) == len(set(out))  # deduped


def test_name_deep_queries_includes_life_events():
    from app.discovery.queries import name_deep_queries

    out = name_deep_queries(["Jane Doe"])
    # Freshness / life-event angles keep records current (incl. death status).
    assert '"Jane Doe" obituary' in out
    assert '"Jane Doe" died' in out
    assert '"Jane Doe" latest news' in out
    assert '"Jane Doe" appointed' in out


def test_onion_extraction_from_ahmia_html():
    from app.discovery.onion import _extract_onions

    html = (
        "<a href=/search/redirect?redirect_url="
        "http%3A%2F%2Fzqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion%2Fw>x</a>"
        " and raw http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/?q=x"
        " clearnet https://github.com/x ignored"
    )
    onions = _extract_onions(html)
    assert all(".onion" in u for u in onions)
    assert any("zqktlwiu" in u for u in onions)
    assert any("duckduckgog" in u for u in onions)
    assert len(onions) == 2  # deduped by host, clearnet excluded


@pytest.mark.anyio
async def test_search_onion_injectable():
    from app.discovery import onion as onionmod

    async def fake_get(url):
        assert "ahmia.fi" in url
        return "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion/"

    res = await onionmod.search_onion("Jane Doe", http_get=fake_get)
    assert res and res[0].endswith(".onion/")


def test_generate_queries_custom_category_and_target():
    # custom/unlisted category + target must still produce queries
    out = q.generate_queries("rwanda", ["lawyers"], ["fax"])
    assert any("lawyers" in x for x in out)  # custom category used literally
    assert any('site:.rw "fax"' == x for x in out)  # custom target quoted literal


def test_term_queries_quotes_literal_terms():
    out = term_queries(["John Doe", "  "])
    assert '"John Doe"' in out
    assert "John Doe photo" in out
    assert all(x.strip() for x in out)


@pytest.mark.anyio
async def test_ddg_fallback_parses_results():
    async def fake_text(url):
        assert "duckduckgo.com" in url
        return (
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.rw%2Fteam">x</a>'
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fportfolio.me%2Fjane">y</a>'
        )

    out = await s.search_candidates_ddg(["q1"], http_get_text=fake_text)
    assert set(out) == {"example.rw", "portfolio.me"}


@pytest.mark.anyio
async def test_search_candidates_free_per_query_fallback(monkeypatch):
    calls = {"duckduckgo": [], "mojeek": []}

    async def ddg(q):
        calls["duckduckgo"].append(q)
        return [] if q == "miss" else [f"https://ddg.test/{q}"]  # "miss" returns nothing

    async def moj(q):
        calls["mojeek"].append(q)
        return [f"https://moj.test/{q}"]

    # pin searxng off; override engine set
    monkeypatch.setattr(s, "get_settings", lambda: type("S", (), {"searxng_url": ""})())
    monkeypatch.setattr(s, "FREE_ENGINES", [("duckduckgo", ddg), ("mojeek", moj)])

    out = await s.search_candidates_free(["a", "miss", "b"], concurrency=1, delay=0)
    # every query hits the reliable engine (ddg) first
    assert set(calls["duckduckgo"]) == {"a", "miss", "b"}
    # only the one that returned nothing falls through to mojeek
    assert calls["mojeek"] == ["miss"]
    assert "ddg.test" in set(out) and "moj.test" in set(out)



def _html(body: str) -> str:
    return f"<html><body>{body}</body></html>"


@pytest.mark.anyio
async def test_evaluate_domain_scores_rich_site():
    rich = _html(
        "<img src='/1.jpg'><img src='/2.jpg'><img src='/3.jpg'>"
        "Call us +250 788 123 456 email info@acme.rw "
        "<a href='https://instagram.com/acme'>IG</a>"
    )

    async def fetch(url):
        return Fetched(status=200, content_type="text/html", body=rich.encode())

    async def robots_ok(url):
        return True

    ev = await evaluate_domain("acme.rw", fetch=fetch, robots=robots_ok, max_pages=1)
    assert ev.reachable
    assert ev.has_images and ev.has_phones and ev.has_emails
    assert ev.score >= 60


@pytest.mark.anyio
async def test_evaluate_domain_unreachable():
    async def fetch(url):
        return Fetched(status=404, content_type="text/html", body=b"")

    ev = await evaluate_domain("dead.example", fetch=fetch, robots=None)
    assert not ev.reachable
    assert ev.score == 0


@pytest.mark.anyio
async def test_evaluate_domain_penalizes_auth_wall():
    walled = _html("Please log in to continue. <img src='/a.jpg'>")

    async def fetch(url):
        return Fetched(status=200, content_type="text/html", body=walled.encode())

    ev = await evaluate_domain("walled.example", fetch=fetch, robots=None, max_pages=1)
    assert ev.requires_auth
    assert ev.score < 60  # auth penalty keeps it below approval threshold
