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


@pytest.fixture(autouse=True)
def _no_slot_leak():
    from app.agents import ratelimit as rl
    rl._active.clear()
    yield
    assert rl._active == {}, "an investigation slot leaked"


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


async def _audit_rows():
    async with _session_maker() as s:
        return (await s.execute(select(AuditLog).where(AuditLog.action == "people.investigate"))).scalars().all()


async def test_streaming_audit_detail(client, auth_headers, seeded):
    await client.post("/enrich/people/investigate", json={"nid": seeded}, headers=auth_headers)
    d = (await _audit_rows())[0].detail
    assert d["query"]["nid"] == seeded and d["query"]["web"] is False
    assert d["agents"] == ["db", "relations"]
    assert d["found"] is True


async def test_audit_survives_disconnect_after_result(client, auth_headers, seeded):
    uid = uuid.uuid4()
    gen = inv._stream(uid, Request(nid=seeded))
    async for chunk in gen:
        if chunk.startswith("event: result"):
            break
    await gen.aclose()
    rows = await _audit_rows()
    assert len(rows) == 1 and rows[0].actor_id == uid


async def test_web_only_writes_audit_and_notes_failure(client, auth_headers, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("offline")
    import app.agents.web_agent as wa
    monkeypatch.setattr(wa, "gather_dossier", boom)
    r = await client.get("/enrich/people/web:Jean%20Paul/investigate", headers=auth_headers)
    assert r.status_code == 200
    b = r.json()
    assert any(n.startswith("web:") for n in b["notes"]), b["notes"]
    d = (await _audit_rows())[0].detail
    assert d == {"query": {"name": "Jean Paul", "web_only": True}, "agents": ["web"], "found": False}


async def test_web_only_name_validation(client, auth_headers):
    r = await client.get("/enrich/people/web:%20%20/investigate", headers=auth_headers)
    assert r.status_code == 400 and r.json() == {"detail": "empty name"}
    r = await client.get("/enrich/people/web:" + "a" * 201 + "/investigate", headers=auth_headers)
    assert r.status_code == 400 and r.json() == {"detail": "name too long"}


async def _drain(gen):
    return [c async for c in gen]


async def test_error_event_is_generic(monkeypatch):
    async def bad(*a, **k):
        raise RuntimeError("postgresql://user:secret@host/db")
    monkeypatch.setattr(inv, "run_investigation", bad)
    out = await _drain(inv._stream(uuid.uuid4(), Request(nid="1")))
    events = _parse("".join(out))
    assert [e for e, _ in events] == ["error"]
    assert events[0][1] == {"detail": "investigation failed"}
    assert "secret" not in "".join(out)


async def test_commit_failure_yields_error_not_result(monkeypatch):
    class S:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return None
        async def commit(self):
            raise RuntimeError("commit boom")
        async def rollback(self):
            S.rolled = True

    async def ok(session, user_id, req, emit, **kw):
        await emit("agent_start", {"agent": "db"})
        return {"person": None}

    monkeypatch.setattr(inv, "async_session_maker", lambda: S())
    monkeypatch.setattr(inv, "run_investigation", ok)
    events = _parse("".join(await _drain(inv._stream(uuid.uuid4(), Request(nid="1")))))
    names = [e for e, _ in events]
    assert "result" not in names and names[-1] == "error"
    assert events[-1][1] == {"detail": "investigation failed"}
    assert S.rolled


async def test_externally_cancelled_run_emits_no_result(monkeypatch):
    async def slow(session, user_id, req, emit, **kw):
        await emit("agent_start", {"agent": "db"})
        await asyncio.sleep(60)

    monkeypatch.setattr(inv, "run_investigation", slow)
    gen = inv._stream(uuid.uuid4(), Request(nid="1"))
    first = await gen.__anext__()
    assert first.startswith("event: agent_start")
    for t in asyncio.all_tasks():
        if t.get_coro().__qualname__.endswith("_stream.<locals>.work"):
            t.cancel()
    rest = _parse("".join([c async for c in gen]))
    assert "result" not in [e for e, _ in rest]


# ---- final fix wave ------------------------------------------------------- #

async def _op_id():
    async with _session_maker() as s:
        return (await s.execute(select(User.id).where(User.email == "op@example.com"))).scalar_one()


async def _seed_audit(uid, n, web=False):
    async with _session_maker() as s:
        for _ in range(n):
            s.add(AuditLog(actor_id=uid, action="people.investigate",
                           detail={"query": {"nid": "1", "web": web}}))
        await s.commit()


async def test_unknown_nid_404_is_still_audited(client, auth_headers):
    nid = _num()
    r = await client.get(f"/enrich/people/{nid}/investigate", headers=auth_headers)
    assert r.status_code == 404
    rows = await _audit_rows()
    assert len(rows) == 1 and rows[0].detail["query"]["nid"] == nid
    assert rows[0].detail["found"] is False


async def test_post_rate_limited_before_streaming(client, auth_headers, seeded):
    await _seed_audit(await _op_id(), 30)
    r = await client.post("/enrich/people/investigate", json={"nid": seeded}, headers=auth_headers)
    assert r.status_code == 429
    assert r.json() == {"detail": "rate limited: too many investigations, retry in a minute"}
    assert len(await _audit_rows()) == 30  # nothing ran


async def test_post_web_rate_limit_only_for_web(client, auth_headers, seeded, monkeypatch):
    import app.agents.web_agent as wa
    monkeypatch.setattr(wa, "search_available", lambda *a, **k: False)
    await _seed_audit(await _op_id(), 5, web=True)
    r = await client.post("/enrich/people/investigate", json={"nid": seeded, "web": True},
                          headers=auth_headers)
    assert r.status_code == 429
    r = await client.post("/enrich/people/investigate", json={"nid": seeded}, headers=auth_headers)
    assert r.status_code == 200 and _parse(r.text)[-1][0] == "result"


async def test_get_click_through_rate_limited(client, auth_headers, seeded):
    await _seed_audit(await _op_id(), 30)
    r = await client.get(f"/enrich/people/{seeded}/investigate", headers=auth_headers)
    assert r.status_code == 429
    r = await client.get("/enrich/people/web:Jean%20Paul/investigate", headers=auth_headers)
    assert r.status_code == 429


async def test_get_click_through_forwards_ambiguity_fields(client, auth_headers, seeded):
    r = await client.get(f"/enrich/people/{seeded}/investigate", headers=auth_headers)
    b = r.json()
    assert b["ambiguous"] is False and b["candidate_count"] == 1


# ---- follow-up: concurrency slots ------------------------------------------ #

from app.agents import ratelimit as rl  # noqa: E402


async def test_post_and_get_429_while_two_runs_held(client, auth_headers, seeded):
    uid = await _op_id()
    a, b = rl.acquire_slot(uid), rl.acquire_slot(uid)
    try:
        r = await client.post("/enrich/people/investigate", json={"nid": seeded}, headers=auth_headers)
        assert r.status_code == 429 and r.json() == {"detail": rl.BUSY}
        r = await client.get(f"/enrich/people/{seeded}/investigate", headers=auth_headers)
        assert r.status_code == 429
        r = await client.get("/enrich/people/web:Jean%20Paul/investigate", headers=auth_headers)
        assert r.status_code == 429
        assert rl._active[uid] == 2
    finally:
        a.release()
        b.release()
    r = await client.post("/enrich/people/investigate", json={"nid": seeded}, headers=auth_headers)
    assert r.status_code == 200 and _parse(r.text)[-1][0] == "result"
    r = await client.get(f"/enrich/people/{seeded}/investigate", headers=auth_headers)
    assert r.status_code == 200


async def test_get_404_and_error_release_slot(client, auth_headers, monkeypatch):
    r = await client.get(f"/enrich/people/{_num()}/investigate", headers=auth_headers)
    assert r.status_code == 404  # fixture asserts no slot leaked


async def test_stream_releases_slot_on_disconnect(monkeypatch):
    class FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return None
        async def commit(self):
            return None
        async def rollback(self):
            return None

    async def slow(session, user_id, req, emit, **kw):
        await emit("agent_start", {"agent": "db"})
        await asyncio.sleep(60)

    monkeypatch.setattr(inv, "async_session_maker", lambda: FakeSession())
    monkeypatch.setattr(inv, "run_investigation", slow)
    uid = uuid.uuid4()
    slot = rl.acquire_slot(uid)
    gen = inv._stream(uid, Request(nid="1"), slot)
    assert (await gen.__anext__()).startswith("event: agent_start")
    assert rl._active[uid] == 1
    await gen.aclose()
    assert uid not in rl._active


async def test_stream_releases_slot_after_error(monkeypatch):
    async def bad(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(inv, "run_investigation", bad)
    uid = uuid.uuid4()
    out = await _drain(inv._stream(uid, Request(nid="1"), rl.acquire_slot(uid)))
    assert "investigation failed" in "".join(out)
    assert uid not in rl._active


async def test_unstarted_stream_slot_released_by_background(client, auth_headers, seeded):
    # the endpoint also releases the slot in a background task, so a response
    # whose body is never iterated cannot leak it (release is idempotent)
    from app.api.investigate import InvestigateBody, investigate
    uid = await _op_id()
    resp = await investigate(InvestigateBody(nid=seeded), operator=User(id=uid, email="x@y.z",
                                                                         password_hash="x"))
    assert rl._active[uid] == 1
    await resp.background()
    assert uid not in rl._active
