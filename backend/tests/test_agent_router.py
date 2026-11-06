import pytest
from app.security.agents.router import route


@pytest.mark.asyncio
async def test_shell_command_routes_to_shell_network():
    r = await route("curl -I https://example.com and show me the headers")
    assert r["agent"] == "shell_network"
    assert r["reason"] == "rule"


@pytest.mark.asyncio
async def test_nid_routes_to_people_identity():
    r = await route("look up 1200480002578150")
    assert r["agent"] == "people_identity"
    assert r["reason"] == "rule"


@pytest.mark.asyncio
async def test_route_query_routes_to_map_geo():
    r = await route("find a route from Kigali to Musanze")
    assert r["agent"] == "map_geo"
    assert r["reason"] == "rule"


@pytest.mark.asyncio
async def test_latest_news_routes_to_web_research():
    r = await route("what's the latest news on this company")
    assert r["agent"] == "web_research"
    assert r["reason"] == "rule"


@pytest.mark.asyncio
async def test_ambiguous_message_falls_back_to_model():
    async def fake_model_classify(message: str) -> str | None:
        return "shell_network"
    r = await route("check example.com", model_classify=fake_model_classify)
    assert r["agent"] == "shell_network"
    assert r["reason"] == "model"


@pytest.mark.asyncio
async def test_model_classify_failure_falls_back_to_general():
    async def failing_model_classify(message: str) -> str | None:
        raise RuntimeError("provider unreachable")
    r = await route("check example.com", model_classify=failing_model_classify)
    assert r["agent"] == "general"
    assert r["reason"] == "fallback"


@pytest.mark.asyncio
async def test_model_classify_unparsable_falls_back_to_general():
    async def junk_model_classify(message: str) -> str | None:
        return "not-a-real-agent-id"
    r = await route("check example.com", model_classify=junk_model_classify)
    assert r["agent"] == "general"
    assert r["reason"] == "fallback"


@pytest.mark.asyncio
async def test_forced_agent_wins_even_if_rules_disagree():
    r = await route("curl -I https://example.com", forced="web_research")
    assert r["agent"] == "web_research"
    assert r["reason"] == "manual"


@pytest.mark.asyncio
async def test_plain_chat_with_no_signals_routes_to_general():
    r = await route("thanks, that makes sense")
    assert r["agent"] == "general"
    assert r["reason"] in ("rule", "fallback")


@pytest.mark.asyncio
async def test_model_classify_timeout_falls_back_to_general(monkeypatch):
    import asyncio
    from app.security.agents import router as router_mod

    monkeypatch.setattr(router_mod, "_MODEL_TIMEOUT_S", 0.05)

    async def hung_model_classify(message: str) -> str | None:
        await asyncio.sleep(5)
        return "shell_network"
    r = await route("check example.com", model_classify=hung_model_classify)
    assert r["agent"] == "general"
    assert r["reason"] == "fallback"
