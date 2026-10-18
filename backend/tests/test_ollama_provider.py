"""Ollama provider: offline unit tests (mock transport) + a live integration
test that runs only when a real Ollama server is reachable."""
from __future__ import annotations

import json

import httpx
import pytest

from app.ai.ollama import (
    GenParams,
    OllamaBadResponse,
    OllamaModelMissing,
    OllamaProvider,
    OllamaTimeout,
    OllamaUnreachable,
)
from app.ai.router import AIMessage


def _provider(handler) -> OllamaProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://ollama.test")
    return OllamaProvider(base_url="http://ollama.test", model="kai-security", client=client)


async def test_status_reachable_and_model_present():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "kai-security:latest"}, {"name": "llama3:latest"}]})

    st = await _provider(handler).status()
    assert st.reachable and st.model_installed and st.to_dict()["ready"] is True
    assert "kai-security:latest" in st.models_available


async def test_status_model_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "llama3:latest"}]})

    st = await _provider(handler).status()
    assert st.reachable is True
    assert st.model_installed is False
    assert st.to_dict()["ready"] is False


async def test_status_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    st = await _provider(handler).status()
    assert st.reachable is False
    assert "ollama_unreachable" in (st.error or "")


async def test_chat_returns_content():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "kai-security"
        assert body["stream"] is False
        assert body["options"]["num_ctx"] == 8192
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hello from kai"}, "done": True})

    out = await _provider(handler).chat([AIMessage(role="user", content="hi")])
    assert out == "hello from kai"


async def test_chat_model_missing_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": 'model "kai-security" not found'})

    with pytest.raises(OllamaModelMissing):
        await _provider(handler).chat([AIMessage(role="user", content="hi")])


async def test_chat_timeout_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(OllamaTimeout):
        await _provider(handler).chat([AIMessage(role="user", content="hi")])


async def test_chat_bad_json_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(OllamaBadResponse):
        await _provider(handler).chat([AIMessage(role="user", content="hi")])


async def test_chat_stream_yields_chunks_and_stops_on_done():
    def handler(request: httpx.Request) -> httpx.Response:
        lines = [
            json.dumps({"message": {"content": "he"}, "done": False}),
            json.dumps({"message": {"content": "llo"}, "done": False}),
            json.dumps({"message": {"content": "!"}, "done": True}),
            json.dumps({"message": {"content": "IGNORED"}, "done": False}),
        ]
        return httpx.Response(200, text="\n".join(lines))

    chunks = [c async for c in _provider(handler).chat_stream([AIMessage(role="user", content="hi")])]
    assert "".join(chunks) == "hello!"
    assert "IGNORED" not in "".join(chunks)


async def test_stream_model_missing_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    with pytest.raises(OllamaModelMissing):
        _ = [c async for c in _provider(handler).chat_stream([AIMessage(role="user", content="hi")])]


# ----- live integration (skips cleanly when Ollama isn't running) --------- #
async def _server_up(base: str) -> bool:
    try:
        async with httpx.AsyncClient(base_url=base, timeout=2.0) as c:
            r = await c.get("/api/tags")
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.asyncio
async def test_live_kai_security_responds():
    from app.core.config import get_settings

    s = get_settings()
    if not await _server_up(s.ollama_base_url):
        pytest.skip(f"Ollama not reachable at {s.ollama_base_url}")
    prov = OllamaProvider()
    st = await prov.status()
    if not st.model_installed:
        pytest.skip(f"model {s.kai_ollama_model} not installed (have: {st.models_available})")
    out = await prov.chat(
        [AIMessage(role="user", content="Reply with exactly the word READY and nothing else.")],
        params=GenParams(num_predict=10),
    )
    assert out.strip(), "empty response from live model"
