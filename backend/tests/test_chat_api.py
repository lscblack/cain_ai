"""Chat API: status, conversation CRUD, and streamed turns (fake provider)."""
from __future__ import annotations

import json

import pytest_asyncio

from app.ai.ollama import OllamaStatus
from app.api.chat import get_chat_provider


class FakeOllama:
    model = "kai-security"

    def __init__(self, replies=None, stream_chunks=None, reachable=True, installed=True):
        self._replies = list(replies or [])
        self._stream = list(stream_chunks or [])
        self._reachable = reachable
        self._installed = installed

    async def status(self):
        return OllamaStatus(
            endpoint="http://fake", model=self.model,
            reachable=self._reachable, model_installed=self._installed,
            models_available=["kai-security:latest"] if self._installed else [],
        )

    async def list_models(self):
        return ["kai-security:latest", "llama3:latest"]

    async def chat_stream(self, messages, *, params=None):
        # Orchestrator (tool mode) consumes one scripted reply per call; the
        # plain path consumes the stream chunks.
        if self._replies:
            yield self._replies.pop(0)
            return
        for c in self._stream:
            yield c


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "chat@example.com", "password": "supersecret1"})
    login = await client.post("/auth/login", json={"email": "chat@example.com", "password": "supersecret1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _use_fake(client, fake):
    client.app.dependency_overrides[get_chat_provider] = lambda: fake


def _parse_sse(text):
    events = []
    cur = {}
    for line in text.splitlines():
        if line.startswith("event: "):
            cur["event"] = line[7:]
        elif line.startswith("data: "):
            cur["data"] = json.loads(line[6:])
        elif line == "" and cur:
            events.append(cur)
            cur = {}
    if cur:
        events.append(cur)
    return events


async def test_status_ready(client, auth_headers):
    _use_fake(client, FakeOllama())
    r = await client.get("/chat/status", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ready"] is True and r.json()["model"] == "kai-security"


async def test_status_model_missing(client, auth_headers):
    _use_fake(client, FakeOllama(installed=False))
    r = await client.get("/chat/status", headers=auth_headers)
    assert r.json()["reachable"] is True and r.json()["model_installed"] is False
    assert r.json()["ready"] is False


async def test_conversation_crud(client, auth_headers):
    _use_fake(client, FakeOllama())
    c = await client.post("/chat/conversations", json={}, headers=auth_headers)
    assert c.status_code == 201
    cid = c.json()["id"]
    lst = (await client.get("/chat/conversations", headers=auth_headers)).json()
    assert any(x["id"] == cid for x in lst)
    patched = await client.patch(f"/chat/conversations/{cid}", json={"title": "Recon"}, headers=auth_headers)
    assert patched.json()["title"] == "Recon"
    got = (await client.get(f"/chat/conversations/{cid}", headers=auth_headers)).json()
    assert got["messages"] == []
    d = await client.delete(f"/chat/conversations/{cid}", headers=auth_headers)
    assert d.status_code == 204
    assert (await client.get(f"/chat/conversations/{cid}", headers=auth_headers)).status_code == 404


async def test_streamed_tool_turn_persists_and_titles(client, auth_headers):
    # Model answers directly (no tool) → deterministic, offline.
    final = json.dumps({"action": "final", "answer": "Here is my grounded answer.", "findings": []})
    _use_fake(client, FakeOllama(replies=[final]))
    c = await client.post("/chat/conversations", json={}, headers=auth_headers)
    cid = c.json()["id"]
    resp = await client.post(
        f"/chat/conversations/{cid}/messages",
        json={"content": "What security tools are available?", "use_tools": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    kinds = [e["event"] for e in events]
    assert "start" in kinds and "final" in kinds and "done" in kinds
    final_ev = [e for e in events if e["event"] == "final"][0]
    assert final_ev["data"]["answer"] == "Here is my grounded answer."
    # persisted: user + assistant, and the conversation is titled from the first message
    detail = (await client.get(f"/chat/conversations/{cid}", headers=auth_headers)).json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant"]
    assert detail["title"].startswith("What security tools")


async def test_streamed_plain_tokens(client, auth_headers):
    _use_fake(client, FakeOllama(stream_chunks=["Hel", "lo ", "world"]))
    c = await client.post("/chat/conversations", json={}, headers=auth_headers)
    cid = c.json()["id"]
    resp = await client.post(
        f"/chat/conversations/{cid}/messages",
        json={"content": "say hello", "use_tools": False},
        headers=auth_headers,
    )
    events = _parse_sse(resp.text)
    tokens = "".join(e["data"]["text"] for e in events if e["event"] == "token")
    assert tokens == "Hello world"
    detail = (await client.get(f"/chat/conversations/{cid}", headers=auth_headers)).json()
    assert detail["messages"][-1]["content"] == "Hello world"


async def test_turn_survives_client_disconnect_and_can_reattach(client, auth_headers):
    """The turn runs server-side: a client that stops reading doesn't cancel it,
    the answer is still persisted, and /stream replays it for a re-attaching client."""
    import asyncio

    final = json.dumps({"action": "final", "answer": "Finished while you were away.", "findings": []})
    _use_fake(client, FakeOllama(replies=[final]))
    cid = (await client.post("/chat/conversations", json={}, headers=auth_headers)).json()["id"]
    async with client.stream("POST", f"/chat/conversations/{cid}/messages",
                             json={"content": "scan something", "use_tools": True},
                             headers=auth_headers) as resp:
        assert resp.status_code == 200
        # read nothing more: simulate the user leaving the page
    for _ in range(50):
        detail = (await client.get(f"/chat/conversations/{cid}", headers=auth_headers)).json()
        if [m["role"] for m in detail["messages"]] == ["user", "assistant"]:
            break
        await asyncio.sleep(0.1)
    assert detail["messages"][-1]["content"] == "Finished while you were away."
    again = await client.get(f"/chat/conversations/{cid}/stream", headers=auth_headers)
    kinds = [e["event"] for e in _parse_sse(again.text)]
    assert "final" in kinds and "done" in kinds
    assert (await client.get("/chat/active", headers=auth_headers)).json() == []


async def _wait_for_pending(conv_id: str, timeout: float = 5.0):
    """Poll the in-process ChatRun for a proposed tool call (same event loop as
    the app under test, so this doesn't need to read the streaming body)."""
    import asyncio
    import uuid as uuid_mod
    from app import chat_runs as chat_runs_mod

    cid = uuid_mod.UUID(conv_id)
    for _ in range(int(timeout / 0.02)):
        run = chat_runs_mod.get_run(cid)
        if run is not None and run.pending_approval:
            return run
        await asyncio.sleep(0.02)
    raise AssertionError("tool call never reached the approval gate")


async def test_tool_call_pauses_for_approval_and_runs_after_approve(client, auth_headers, monkeypatch):
    """The operator sees the real command BEFORE it runs, and approving it is
    what makes it actually execute."""
    import asyncio
    from app.security import service as service_mod

    tool_call = json.dumps({"action": "tool", "operation": "cve.lookup",
                            "params": {"ecosystem": "PyPI", "package": "requests"}})
    final = json.dumps({"action": "final", "answer": "No advisories found.", "findings": []})
    _use_fake(client, FakeOllama(replies=[tool_call, final]))

    calls = []

    async def fake_run_operation(session, *, user_id, op_key, params, conversation_id=None):
        calls.append(op_key)
        return {"ok": True, "status": "ok", "tool": "osv", "operation": op_key, "result": {"vulns": []}}

    monkeypatch.setattr(service_mod, "run_operation", fake_run_operation)

    cid = (await client.post("/chat/conversations", json={}, headers=auth_headers)).json()["id"]
    task = asyncio.ensure_future(client.post(
        f"/chat/conversations/{cid}/messages",
        json={"content": "check requests for known CVEs", "use_tools": True}, headers=auth_headers,
    ))
    run = await _wait_for_pending(cid)
    assert not calls, "must not run before the operator approves it"
    assert run.pending_approval["operation"] == "cve.lookup"
    assert run.pending_approval["preview"]["ok"] is True
    assert run.pending_approval["preview"]["tool"] == "osv"

    appr = await client.post(f"/chat/conversations/{cid}/approve", json={"approved": True}, headers=auth_headers)
    assert appr.status_code == 200 and appr.json() == {"ok": True, "approved": True}

    resp = await task
    events = _parse_sse(resp.text)
    kinds = [e["event"] for e in events]
    assert kinds.index("tool_proposed") < kinds.index("tool_call") < kinds.index("tool_result")
    assert calls == ["cve.lookup"]
    assert "done" in kinds


async def test_declining_a_proposed_tool_call_skips_it(client, auth_headers, monkeypatch):
    import asyncio
    from app.security import service as service_mod

    tool_call = json.dumps({"action": "tool", "operation": "cve.lookup",
                            "params": {"ecosystem": "PyPI", "package": "requests"}})
    final = json.dumps({"action": "final", "answer": "I could not check — you declined the lookup.", "findings": []})
    _use_fake(client, FakeOllama(replies=[tool_call, final]))

    calls = []
    monkeypatch.setattr(service_mod, "run_operation",
                        lambda *a, **k: calls.append(1) or {"ok": True, "status": "ok"})

    cid = (await client.post("/chat/conversations", json={}, headers=auth_headers)).json()["id"]
    task = asyncio.ensure_future(client.post(
        f"/chat/conversations/{cid}/messages",
        json={"content": "check requests for known CVEs", "use_tools": True}, headers=auth_headers,
    ))
    await _wait_for_pending(cid)
    appr = await client.post(f"/chat/conversations/{cid}/approve", json={"approved": False}, headers=auth_headers)
    assert appr.json()["approved"] is False

    resp = await task
    kinds = [e["event"] for e in _parse_sse(resp.text)]
    assert "tool_proposed" in kinds and "tool_denied" in kinds and "tool_call" not in kinds
    assert calls == []


async def test_auto_approve_skips_the_gate(client, auth_headers, monkeypatch):
    """The old (pre-approval) behaviour is still available per-message."""
    from app.security import service as service_mod

    final = json.dumps({"action": "final", "answer": "Here you go.", "findings": []})
    _use_fake(client, FakeOllama(replies=[final]))
    monkeypatch.setattr(service_mod, "run_operation", lambda *a, **k: {"ok": True, "status": "ok"})

    cid = (await client.post("/chat/conversations", json={}, headers=auth_headers)).json()["id"]
    resp = await client.post(
        f"/chat/conversations/{cid}/messages",
        json={"content": "hi", "use_tools": True, "auto_approve": True}, headers=auth_headers,
    )
    kinds = [e["event"] for e in _parse_sse(resp.text)]
    assert "tool_proposed" not in kinds and "done" in kinds


async def test_approve_with_nothing_pending_is_a_conflict(client, auth_headers):
    cid = (await client.post("/chat/conversations", json={}, headers=auth_headers)).json()["id"]
    r = await client.post(f"/chat/conversations/{cid}/approve", json={"approved": True}, headers=auth_headers)
    assert r.status_code == 404  # no run at all for this conversation yet
