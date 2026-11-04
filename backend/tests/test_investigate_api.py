"""Person-investigation API: streaming POST and one-hop GET."""
from __future__ import annotations

import asyncio
import json
import random
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.api.investigate as inv
from app.agents.base import Request
from app.database.models.audit import AuditLog
from app.database.models.enrich import Person
from app.database.models.user import User
from tests.conftest import _session_maker

pytestmark = pytest.mark.asyncio


def _num() -> str:
    return "1" + "".join(str(random.randint(0, 9)) for _ in range(15))


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post("/auth/login", json={"email": "op@example.com", "password": "supersecret1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(autouse=True)
async def _patch_maker(client, monkeypatch):
    monkeypatch.setattr(inv, "async_session_maker", _session_maker)


@pytest_asyncio.fixture
async def seeded():
    nid = _num()
    async with _session_maker() as s:
        s.add(Person(nid=nid, raw={}, forenames="JEAN", surnames="NZEYIMANA"))
        await s.commit()
    return nid


def _parse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev:
            out.append((ev, data))
    return out


async def test_requires_auth(client):
    assert (await client.post("/enrich/people/investigate", json={"nid": "1"})).status_code == 401
    assert (await client.get("/enrich/people/123/investigate")).status_code == 401


async def test_empty_request_400(client, auth_headers):
    r = await client.post("/enrich/people/investigate", json={"nid": "  ", "name": ""},
                          headers=auth_headers)
    assert r.status_code == 400
    assert r.json() == {"detail": "provide a nid, phone, or name"}


async def test_investigate_streams_agent_events_then_result(client, auth_headers, seeded):
    r = await client.post("/enrich/people/investigate", json={"nid": seeded}, headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse(r.text)
    names = [e for e, _ in events]
    assert "agent_start" in names and "agent_done" in names
    assert {"agent": "db"} in [d for e, d in events if e == "agent_done"]
    assert names[-1] == "result"
    assert events[-1][1]["person"]["nid"] == seeded


async def test_streaming_commits_audit_row(client, auth_headers, seeded):
    r = await client.post("/enrich/people/investigate", json={"nid": seeded}, headers=auth_headers)
    assert r.status_code == 200
    async with _session_maker() as s:
        uid = (await s.execute(select(User.id).where(User.email == "op@example.com"))).scalar_one()
        rows = (await s.execute(select(AuditLog).where(AuditLog.action == "people.investigate"))).scalars().all()
    assert rows and rows[0].actor_id == uid


async def test_click_through_one_hop(client, auth_headers, seeded):
    r = await client.get(f"/enrich/people/{seeded}/investigate", headers=auth_headers)
    assert r.status_code == 200
    b = r.json()
    assert b["agents_run"] == ["db", "relations"]
    assert b["person"]["nid"] == seeded
    for k in ("kin", "associates", "nodes"):
        assert k in b["relations"]
    assert "facts" in b and "notes" in b


async def test_click_through_unknown_nid_404(client, auth_headers):
    r = await client.get(f"/enrich/people/{_num()}/investigate", headers=auth_headers)
    assert r.status_code == 404
    assert r.json() == {"detail": "person_not_found"}


async def test_web_only_node_returns_card_not_404(client, auth_headers, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("offline")
    import app.agents.web_agent as wa
    monkeypatch.setattr(wa, "gather_dossier", boom)
    monkeypatch.setattr(wa, "search_available", lambda *a, **k: False)
    r = await client.get("/enrich/people/web:Jean%20Paul%20Nzeyimana/investigate", headers=auth_headers)
    assert r.status_code == 200
    b = r.json()
    assert b["web_only"] is True and b["person"] is None
    assert b["name"] == "Jean Paul Nzeyimana"
    assert "findings" in b and "spouse_candidates" in b and "notes" in b
    assert b["lookup_hint"] == "search this name in the system"


async def test_client_disconnect_cancels_run(monkeypatch):
    state = {}
    closed = {}

    class FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            closed["closed"] = True
        async def commit(self):
            closed["committed"] = True
        async def rollback(self):
            closed["rolled_back"] = True

    async def slow(session, user_id, req, emit, **kw):
        state["task"] = asyncio.current_task()
        await emit("agent_start", {"agent": "db"})
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    monkeypatch.setattr(inv, "async_session_maker", lambda: FakeSession())
    monkeypatch.setattr(inv, "run_investigation", slow)
    gen = inv._stream(uuid.uuid4(), Request(nid="1"))
    first = await gen.__anext__()
    assert first.startswith("event: agent_start")
    await gen.aclose()
    await asyncio.sleep(0)
    assert state["task"].done() and state.get("cancelled")
    assert closed.get("closed") and not closed.get("committed")
