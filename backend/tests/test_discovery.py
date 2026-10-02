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


def test_term_queries_quotes_literal_terms():
    out = term_queries(["John Doe", "  "])
    assert '"John Doe"' in out
    assert "John Doe photo" in out
    assert all(x.strip() for x in out)


@pytest.mark.anyio
async def test_search_candidates_dedupes_by_domain(monkeypatch):
    monkeypatch.setattr(s, "get_settings", lambda: type("S", (), {"serpapi_api_key": "x"})())

    async def fake_get(url, params):
        return {"organic_results": [
            {"link": "https://acme.rw/a"},
            {"link": "https://acme.rw/b"},  # same domain -> deduped
            {"link": "https://other.co.ke/x"},
        ]}

    out = await s.search_candidates(["q1"], http_get=fake_get)
    assert set(out) == {"acme.rw", "other.co.ke"}


@pytest.mark.anyio
async def test_search_candidates_empty_without_key(monkeypatch):
    monkeypatch.setattr(s, "get_settings", lambda: type("S", (), {"serpapi_api_key": ""})())
    out = await s.search_candidates(["q1"], http_get=None)
    assert out == {}


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
