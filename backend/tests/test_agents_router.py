import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

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
    events = []

    async def emit(ev, payload):
        events.append((ev, payload))
    res = await run_investigation(db_session, uid,
                                  Request(nid=tag, image=b"\xff\xd8SENTINEL" * 10),
                                  emit, agents=_fakes())
    assert "SENTINEL" not in repr(res) and "SENTINEL" not in repr(events)
    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "people.investigate",
                               AuditLog.actor_id == uid))).scalars().all()
    assert len(rows) == 1
    d = rows[0].detail
    assert d["query"]["has_image"] is True and d["query"]["nid"] == tag
    assert "image" not in d["query"] and "SENTINEL" not in repr(d)
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


class SqlAgent(Fake):
    def __init__(self, name, sql, **kw):
        super().__init__(name, **kw)
        self.sql = sql

    async def run(self, ctx):
        await ctx.session.execute(text(self.sql))
        return AgentResult(self.name, True, [_f("ok")], {"ok": 1})


async def _audit_count(db_session, uid):
    return len((await db_session.execute(select(AuditLog).where(
        AuditLog.action == "people.investigate", AuditLog.actor_id == uid))).scalars().all())


async def test_session_usable_after_timeout(db_session, monkeypatch):
    monkeypatch.setattr(router, "PER_AGENT_TIMEOUT", 0.2)
    uid = uuid.uuid4()
    ag = _fakes(web=SqlAgent("web", "select pg_sleep(2)"),
                relations=SqlAgent("relations", "select 1"))
    out = await run_investigation(db_session, uid, Request(nid="1", web=True),
                                  _emit_none, agents=ag)
    assert any(n.startswith("web: timed out") for n in out["notes"])
    assert out["relations"] == {"ok": 1}
    assert "audit failed" not in out["notes"]
    assert await _audit_count(db_session, uid) == 1


async def test_session_usable_after_sql_error(db_session):
    uid = uuid.uuid4()
    ag = _fakes(web=SqlAgent("web", "select * from definitely_missing_table"),
                relations=SqlAgent("relations", "select 1"))
    out = await run_investigation(db_session, uid, Request(nid="1", web=True),
                                  _emit_none, agents=ag)
    assert any(n.startswith("web:") for n in out["notes"])
    assert out["relations"] == {"ok": 1}
    assert "audit failed" not in out["notes"]
    assert await _audit_count(db_session, uid) == 1


async def test_failed_agent_facts_renumbered_unique(db_session):
    ag = _fakes(web=Fake("web", [_f("w1", "web"), _f("w2", "web")], ok=False, error="partial"))
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid="1", web=True),
                                  _emit_none, agents=ag)
    ids = [f["id"] for f in out["facts"]]
    assert ids == ["F1", "F2", "F3", "F4", "F5"] and len(set(ids)) == 5
    assert "web: partial" in out["notes"]


async def test_missing_agent_noted(db_session):
    events = []

    async def emit(ev, payload):
        events.append((ev, payload["agent"]))
    ag = _fakes()
    del ag["web"]
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid="1", web=True),
                                  emit, agents=ag)
    assert "web: agent unavailable" in out["notes"]
    assert ("agent_error", "web") in events
    assert out["relations"] is not None


async def test_cancelled_error_propagates(db_session):
    ag = _fakes(web=Fake("web", exc=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await run_investigation(db_session, uuid.uuid4(), Request(nid="1", web=True),
                                _emit_none, agents=ag)


# ---- final fix wave ------------------------------------------------------- #

def _letters() -> str:
    return "".join(chr(65 + int(c, 16)) for c in uuid.uuid4().hex[:8])


async def _seed_family(db_session):
    t = _letters()
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
    return sid, t


@pytest.mark.parametrize("web_sql", ["select pg_sleep(2)", "select * from definitely_missing_table"])
async def test_real_relations_survive_web_failure(db_session, monkeypatch, web_sql):
    # F1: the rollback after a failed web agent expires ctx.person; the router
    # must re-load it so the REAL RelationsAgent still produces kin.
    monkeypatch.setitem(router.AGENT_TIMEOUTS, "web", 0.3)
    sid, t = await _seed_family(db_session)
    ag = {"db": DbAgent(), "web": SqlAgent("web", web_sql), "relations": RelationsAgent()}
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid=sid, web=True),
                                  _emit_none, agents=ag)
    assert any(n.startswith("web:") for n in out["notes"])
    assert not any(n.startswith("relations:") for n in out["notes"]), out["notes"]
    assert "greenlet" not in repr(out["notes"]).lower()
    rel = out["relations"]
    assert rel is not None
    assert [p["nid"] for p in rel["kin"]["partners"]] == [f"p{t}"]
    assert {c["nid"] for c in rel["kin"]["children"]} == {f"c0{t}", f"c1{t}"}


async def test_result_forwards_counts_and_flags(db_session):
    people = [{"nid": str(i)} for i in range(7)]
    ag = _fakes(
        db=Fake("db", [_f("a")], {"people": people, "person_nid": "0", "ambiguous": True}),
        web=Fake("web", [], {"findings": [], "spouse_names": [], "name_collision_warning": True}),
        analyst=Fake("analyst", [], {"analysis": "x", "dropped": ["SMEAR one.", "SMEAR two."],
                                      "omitted_facts": 3}))
    out = await run_investigation(db_session, uuid.uuid4(),
                                  Request(name="X Y", web=True, analyse=True), _emit_none, agents=ag)
    assert out["candidate_count"] == 7 and out["people"] == people[:5]
    assert out["person"] == {"nid": "0"}
    assert out["ambiguous"] is True and out["name_collision_warning"] is True
    assert out["analysis_dropped_count"] == 2 and out["omitted_facts"] == 3
    assert "SMEAR" not in repr(out)


async def test_result_flag_defaults(db_session):
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid="1"), _emit_none,
                                  agents=_fakes())
    assert out["ambiguous"] is False and out["name_collision_warning"] is False
    assert out["analysis_dropped_count"] == 0 and out["omitted_facts"] == 0
    assert out["candidate_count"] == 1


def test_default_timeouts():
    assert router.PER_AGENT_TIMEOUT == 25.0
    assert router.AGENT_TIMEOUTS["analyst"] == 180.0
    assert router._timeout_for("web") == router.PER_AGENT_TIMEOUT
    assert router._timeout_for("analyst") == 180.0


async def test_analyst_uses_its_own_timeout(db_session, monkeypatch):
    monkeypatch.setattr(router, "PER_AGENT_TIMEOUT", 0.05)
    monkeypatch.setitem(router.AGENT_TIMEOUTS, "analyst", 2.0)
    ag = _fakes(analyst=Fake("analyst", [], {"analysis": "slow"}, sleep=0.3))
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid="1", analyse=True),
                                  _emit_none, agents=ag)
    assert out["analysis"] == "slow"
    assert not any(n.startswith("analyst:") for n in out["notes"])


async def test_analyst_timeout_label_uses_its_timeout(db_session, monkeypatch):
    monkeypatch.setitem(router.AGENT_TIMEOUTS, "analyst", 0.05)
    ag = _fakes(analyst=Fake("analyst", [], {"analysis": "slow"}, sleep=1))
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid="1", analyse=True),
                                  _emit_none, agents=ag)
    assert "analyst: timed out after 0.05s" in out["notes"]
    assert out["analysis"] is None


async def test_reported_spouse_fact_not_duplicated(db_session, monkeypatch):
    # F9: the web agent emits the "reported spouse" fact; relations must not re-emit it.
    import app.agents.web_agent as wa
    from app.agents.web_agent import WebAgent
    t = _letters()
    sid = str(uuid.uuid4().int)[:16]
    db_session.add(Person(nid=sid, raw={}, forenames="JEAN", surnames=f"NZEYIMANA{t}"))
    db_session.add(Person(nid=f"g{t}", raw={}, forenames="GRACE", surnames=f"MUKAMANA{t}"))
    await db_session.commit()

    async def fake_dossier(session, term, *, public=False, as_name=False):
        return {"faces": [], "titles": [], "orgs": [], "locations": [], "pages": [
            {"url": "https://a.example/p", "title": "Profile",
             "description": f"Jean Nzeyimana{t} is married to Grace Mukamana{t}."}]}
    monkeypatch.setattr(wa, "gather_dossier", fake_dossier)
    monkeypatch.setattr(wa, "search_available", lambda: False)
    ag = {"db": DbAgent(), "web": WebAgent(), "relations": RelationsAgent()}
    out = await run_investigation(db_session, uuid.uuid4(), Request(nid=sid, web=True),
                                  _emit_none, agents=ag)
    sp = [f for f in out["facts"] if f["claim"] == "reported spouse"]
    assert [f["value"] for f in sp] == [f"Grace Mukamana{t}"]
    assert sp[0]["source"] == "web" and sp[0]["source_ref"] == "https://a.example/p"
    node = next(n for n in out["relations"]["nodes"] if n["nid"] == f"g{t}")
    assert node["in_system"] is True and node["source_ref"] == "https://a.example/p"
    assert node["fact_id"] == sp[0]["id"] and node["relation"] == "reported spouse"
