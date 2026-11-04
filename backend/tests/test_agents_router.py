import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.agents import router
from app.agents.base import AgentResult, Fact, Request
from app.agents.relations_agent import RelationsAgent
from app.agents.db_agent import DbAgent
from app.agents.router import investigate_nid, run_investigation, select_agents
from app.database.models.audit import AuditLog
from app.database.models.enrich import Person
from app.database.repositories.audit_repo import AuditRepository


def _f(claim="c", src="db"):
    return Fact("", claim, "v", src, "ref", datetime.now(timezone.utc).isoformat(), 50)


class Fake:
    def __init__(self, name, facts=(), data=None, ok=True, error=None, sleep=0, exc=None):
        self.name, self._facts, self._data = name, list(facts), data or {}
        self._ok, self._err, self._sleep, self._exc = ok, error, sleep, exc
        self.seen_ids = None

    def can_handle(self, ctx):
        return True

    async def run(self, ctx):
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._exc:
            raise self._exc
        self.seen_ids = [f.id for r in ctx.results.values() for f in r.facts]
        return AgentResult(self.name, self._ok, list(self._facts), dict(self._data), self._err)


def _fakes(**over):
    base = {
        "db": Fake("db", [_f("a"), _f("b")], {"people": [{"nid": "1"}], "person_nid": "1"}),
        "web": Fake("web", [_f("w", "web")], {"findings": [{"x": 1}], "spouse_names": ["S"]}),
        "relations": Fake("relations", [_f("r", "inference")], {"kin": []}),
        "analyst": Fake("analyst", [], {"analysis": "text"}),
    }
    base.update(over)
    return base


async def _emit_none(*a):
    return None


def test_select_nid_only_found():
    assert select_agents(Request(nid="1"), True) == ["db", "relations"]


def test_select_nid_only_not_found():
    assert select_agents(Request(nid="1"), False) == ["db", "web"]


def test_select_web_and_analyse_analyst_last():
    r = select_agents(Request(nid="1", web=True, analyse=True), True)
    assert r == ["db", "web", "relations", "analyst"]


def test_select_no_identifiers_empty():
    assert select_agents(Request(web=True, analyse=True), True) == []


async def test_agent_timeout_degrades(db_session, monkeypatch):
    monkeypatch.setattr(router, "PER_AGENT_TIMEOUT", 0.05)
    ag = _fakes(web=Fake("web", sleep=1))
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid="1", web=True),
                                  _emit_none, agents=ag)
    assert out["person"] == {"nid": "1"}
    assert any(n.startswith("web: timed out after") for n in out["notes"])


async def test_agent_exception_degrades(db_session):
    ag = _fakes(web=Fake("web", exc=RuntimeError("boom")))
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid="1", web=True),
                                  _emit_none, agents=ag)
    assert "web: boom" in out["notes"]
    assert out["relations"] is not None


async def test_facts_renumbered_globally_in_order(db_session):
    ag = _fakes()
    out = await run_investigation(db_session, uuid.uuid4(),
                                  Request(nid="1", web=True, analyse=True), _emit_none, agents=ag)
    ids = [f["id"] for f in out["facts"]]
    assert ids == ["F1", "F2", "F3", "F4"]
    assert [f["claim"] for f in out["facts"]] == ["a", "b", "w", "r"]
    assert ag["analyst"].seen_ids == ids
    assert out["agents_run"] == ["db", "web", "relations", "analyst"]
    assert out["analysis"] == "text"
    assert out["spouse_candidates"] == ["S"]


async def test_audit_written_without_image_bytes(db_session):
    uid = uuid.uuid4()
    tag = uuid.uuid4().hex
    await run_investigation(db_session, uid, Request(nid=tag, image=b"\x89PNG" * 10),
                            _emit_none, agents=_fakes())
    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "people.investigate",
                               AuditLog.actor_id == uid))).scalars().all()
    assert len(rows) == 1
    d = rows[0].detail
    assert d["query"]["has_image"] is True and d["query"]["nid"] == tag
    assert "image" not in d["query"] and "PNG" not in str(d)
    assert d["agents"][0] == "db"


async def test_person_returned_when_web_fails(db_session):
    ag = _fakes(web=Fake("web", ok=False, error="offline"))
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid="1", web=True),
                                  _emit_none, agents=ag)
    assert out["person"] == {"nid": "1"}
    assert "web: offline" in out["notes"]
    assert out["web_findings"] == []


async def test_not_found_note(db_session):
    ag = _fakes(db=Fake("db", data={"people": [], "person_nid": None}))
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid="1"),
                                  _emit_none, agents=ag)
    assert out["person"] is None
    assert "no matching person found in the saved database" in out["notes"]
    assert out["agents_run"] == ["db", "web"]


async def test_audit_failure_does_not_break(db_session, monkeypatch):
    async def boom(self, *a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(AuditRepository, "record", boom)
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid="1"),
                                  _emit_none, agents=_fakes())
    assert out["person"] == {"nid": "1"}
    assert "audit failed" in out["notes"]


async def test_events_emitted_in_order(db_session):
    events = []

    async def emit(ev, payload):
        events.append((ev, payload["agent"]))
    ag = _fakes(web=Fake("web", ok=False, error="x"))
    await run_investigation(db_session, uuid.uuid4(), Request(nid="1", web=True),
                            emit, agents=ag)
    assert events == [("agent_start", "db"), ("agent_done", "db"),
                      ("agent_start", "web"), ("agent_error", "web"),
                      ("agent_start", "relations"), ("agent_done", "relations")]


async def test_integration_real_agents(db_session):
    t = uuid.uuid4().hex[:8].upper()
    sid = str(uuid.uuid4().int)[:16]
    dad, mum = f"JEAN NZEYIMANA{t}", f"MARIE UWASE{t}"
    rows = [
        Person(nid=sid, raw={}, forenames="JEAN", surnames=f"NZEYIMANA{t}", sex="M",
               date_of_birth="1970"),
        Person(nid=f"p{t}", raw={}, forenames="MARIE", surnames=f"UWASE{t}", sex="F",
               date_of_birth="1972"),
    ] + [Person(nid=f"c{i}{t}", raw={}, forenames="K", surnames="X", father_names=dad,
                mother_names=mum, date_of_birth="2000") for i in range(2)]
    for r in rows:
        db_session.add(r)
    await db_session.commit()
    ag = {"db": DbAgent(), "relations": RelationsAgent()}
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid=sid),
                                  _emit_none, agents=ag)
    assert out["person"]["nid"] == sid
    out2 = await investigate_nid(db_session, uuid.uuid4(), sid)
    assert out2["agents_run"] == ["db", "relations"]
    assert out["relations"] is not None
    assert out["agents_run"] == ["db", "relations"]
    ids = [f["id"] for f in out["facts"]]
    assert len(ids) == len(set(ids)) and ids[0] == "F1"
