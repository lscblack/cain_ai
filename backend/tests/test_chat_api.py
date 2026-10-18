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
