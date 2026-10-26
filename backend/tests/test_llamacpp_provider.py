"""llama.cpp provider: OpenAI-style streaming, status states, GPU detection (offline)."""
from __future__ import annotations

import json

import httpx
import pytest

from app.ai.llamacpp import LlamaCppProvider
from app.ai.ollama import GenParams, OllamaUnreachable, get_ollama_provider
from app.ai.router import AIMessage


def _provider(handler, **kw):
    client = httpx.AsyncClient(base_url="http://llama", transport=httpx.MockTransport(handler))
    return LlamaCppProvider(client=client, base_url="http://llama", model="kai", **kw)


def _sse(*chunks):
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in chunks]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


async def test_stream_yields_tokens_and_strips_think():
    def handler(req):
        body = json.loads(req.content)
        assert body["stream"] is True and body["chat_template_kwargs"] == {"enable_thinking": False}
        return httpx.Response(200, content=_sse("<think>", "hmm", "</think>\n", "Hel", "lo"))

    p = _provider(handler)
    out = [c async for c in p.chat_stream([AIMessage(role="user", content="hi")], params=GenParams())]
    assert "".join(out) == "Hello"


async def test_chat_non_stream():
    p = _provider(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "<think>x</think>pong"}}]}))
    assert await p.chat([AIMessage(role="user", content="ping")]) == "pong"


async def test_status_ready_loading_and_offline(tmp_path):
    log = tmp_path / "llama.log"
    log.write_text("ggml_vulkan: 0 = Intel(R) UHD Graphics 770 (ADL-S GT1) (Intel open-source Mesa driver) | uma: 1\n"
                   "load_tensors: offloaded 37/37 layers to GPU\n")

    def ok(req):
        if req.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"data": [{"id": "kai"}]})

    p = _provider(ok)
    p._log_path = str(log)
    st = (await p.status()).to_dict()
    assert st["ready"] and st["backend"] == "llamacpp" and st["accelerator"] == "GPU (Intel(R) UHD Graphics 770) · 37/37 layers"

    log.write_text("llama_prepare_model_devices: using device Vulkan0 (Intel(R) UHD Graphics (ADL-S GT1)) (0000:00:02.0) - 16875 MiB free\n"
                   "load_tensors: offloaded 37/37 layers to GPU\n")
    assert (await p.status()).accelerator == "GPU (Intel(R) UHD Graphics) · 37/37 layers"

    log.write_text("load_tensors: offloaded 0/37 layers to GPU\n")
    assert (await p.status()).accelerator == "CPU"

    loading = _provider(lambda r: httpx.Response(503, json={"error": "Loading model"}))
    st = (await loading.status()).to_dict()
    assert st["reachable"] and not st["ready"] and "loading" in st["error"]

    def boom(req):
        raise httpx.ConnectError("refused")

    st = (await _provider(boom).status()).to_dict()
    assert not st["reachable"] and not st["ready"]


async def test_chat_while_server_down_raises_typed_error():
    def boom(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(OllamaUnreachable):
        await _provider(boom).chat([AIMessage(role="user", content="x")])


def test_backend_switch(monkeypatch):
    import app.ai.ollama as mod
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "kai_llm_backend", "llamacpp")
    monkeypatch.setattr(mod, "_provider", None)
    assert get_ollama_provider().name == "llamacpp"
    monkeypatch.setattr(get_settings(), "kai_llm_backend", "ollama")
    monkeypatch.setattr(mod, "_provider", None)
    assert get_ollama_provider().name == "ollama"


def _two_servers(handlers):
    """Provider with a CPU-like and an iGPU-like server, each backed by its own mock."""
    from app.ai.llamacpp import _Server

    p = LlamaCppProvider(base_url="http://cpu", model="kai")
    p._servers = [_Server("http://cpu", 1.0), _Server("http://igpu", 1.0)]
    p._client_for = lambda srv: httpx.AsyncClient(
        base_url=srv.url, transport=httpx.MockTransport(handlers[srv.url]))
    return p


def _ok(tag):
    def handler(req):
        if json.loads(req.content)["stream"]:
            return httpx.Response(200, content=_sse(tag))
        return httpx.Response(200, json={"choices": [{"message": {"content": tag}}]})
    return handler


async def test_conversations_spread_across_both_servers_and_stay_pinned():
    p = _two_servers({"http://cpu": _ok("C"), "http://igpu": _ok("G")})
    a = [AIMessage(role="user", content="conversation A")]
    b = [AIMessage(role="user", content="conversation B")]
    sa = p._pick(a)
    sa.inflight += 1                      # A is generating on its server…
    sb = p._pick(b)                       # …so B goes to the other chip
    assert sa is not sb
    sa.inflight -= 1
    assert p._pick(a) is sa and p._pick(b) is sb   # each conversation stays on its server (warm cache)
    out_a = "".join([c async for c in p.chat_stream(a)])
    out_b = "".join([c async for c in p.chat_stream(b)])
    assert {out_a, out_b} == {"C", "G"}


async def test_failover_when_one_server_is_down():
    def down(req):
        raise httpx.ConnectError("refused")

    p = _two_servers({"http://cpu": down, "http://igpu": _ok("G")})
    msgs = [AIMessage(role="user", content="hello")]
    p._sticky.clear()
    out = "".join([c async for c in p.chat_stream(msgs)])
    assert out == "G"
    assert not p._servers[0].healthy       # primary is skipped for a while
    assert await p.chat(msgs) == "G"
