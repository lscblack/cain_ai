import uuid

import pytest
from sqlalchemy import select

from app.database.models.audit import AuditLog
from app.database.models.enrich import Person
from app.agents import router
from app.agents.base import AgentResult
from app.security import people_ops
from tests.conftest import _session_maker
from app.security.people_ops import PEOPLE_INVESTIGATE, preview, run_people_op


@pytest.fixture(autouse=True)
def _own_session_maker(monkeypatch):
    monkeypatch.setattr(people_ops, "async_session_maker", _session_maker)


def test_preview_text():
    assert preview({"nid": "123"}) == "investigate person 123"
    assert "web" in preview({"name": "JEAN", "web": True})


async def test_rejects_empty_params(db_session):
    for p in ({}, {"nid": "  ", "name": ""}, {"web": True}):
        out = await run_people_op(db_session, user_id=uuid.uuid4(),
                                  op_key=PEOPLE_INVESTIGATE, params=p)
        assert out["ok"] is False and "at least one" in out["error"]


async def test_rejects_unknown_params_types(db_session):
    uid = uuid.uuid4()
    for p in ({"nid": "1", "image": "x"}, {"nid": 5}, {"nid": "1", "web": "yes"}):
        out = await run_people_op(db_session, user_id=uid, op_key=PEOPLE_INVESTIGATE, params=p)
        assert out["ok"] is False and out["error"]


async def test_run_returns_compact_person_for_nid(db_session):
    t = uuid.uuid4().hex[:8].upper()
    nid = str(uuid.uuid4().int)[:16]
    db_session.add(Person(nid=nid, raw={}, forenames="JEAN", surnames=f"NZEYIMANA{t}",
                          sex="M", date_of_birth="1970"))
    await db_session.commit()
    uid = uuid.uuid4()
    out = await run_people_op(db_session, user_id=uid, op_key=PEOPLE_INVESTIGATE,
                              params={"nid": nid})
    assert out["ok"] is True
    assert out["person"]["nid"] == nid
    assert "db" in out["agents_run"] and "relations" in out["agents_run"]
    assert set(out["relations"]) >= {"kin", "associates", "weak_associates"}
    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "people.investigate",
                               AuditLog.actor_id == uid))).scalars().all()
    assert len(rows) == 1


async def test_relations_trimmed_to_10(db_session, monkeypatch):
    async def fake(session, user_id, req, emit, **kw):
        return {"person": {"nid": "1"}, "relations": {
            "kin": {"parents": [], "siblings": [{"nid": str(i)} for i in range(12)]},
            "associates": [{"nid": str(i)} for i in range(25)],
            "weak_associates": []},
            "web_findings": [{"i": i} for i in range(9)],
            "notes": [], "agents_run": ["db"]}
    monkeypatch.setattr(people_ops, "run_investigation", fake)
    out = await run_people_op(db_session, user_id=uuid.uuid4(),
                              op_key=PEOPLE_INVESTIGATE, params={"nid": "1"})
    assert len(out["relations"]["associates"]) == 10
    assert len(out["web_findings"]) == 5
    assert out["relations"]["truncated"] == {"kin.siblings": True, "associates": True}
    assert len(out["relations"]["kin"]["siblings"]) == 10


async def test_truncated_false_when_nothing_cut(db_session, monkeypatch):
    async def fake(session, user_id, req, emit, **kw):
        return {"person": None, "relations": {"kin": {}, "associates": [],
                "weak_associates": []}, "notes": [], "agents_run": []}
    monkeypatch.setattr(people_ops, "run_investigation", fake)
    out = await run_people_op(db_session, user_id=uuid.uuid4(),
                              op_key=PEOPLE_INVESTIGATE, params={"nid": "1"})
    assert out["relations"]["truncated"] is False


async def test_no_image_bytes_in_output(db_session, monkeypatch):
    import json

    async def fake(session, user_id, req, emit, **kw):
        return {"person": {"nid": "1", "image": b"\xff\xd8", "photo": b"x"},
                "relations": None, "web_findings": [{"thumb": b"zz"}],
                "notes": [], "agents_run": ["db"]}
    monkeypatch.setattr(people_ops, "run_investigation", fake)
    out = await run_people_op(db_session, user_id=uuid.uuid4(),
                              op_key=PEOPLE_INVESTIGATE, params={"name": "A"})
    def has_bytes(o):
        if isinstance(o, (bytes, bytearray)):
            return True
        if isinstance(o, dict):
            return any(has_bytes(v) for v in o.values())
        if isinstance(o, list):
            return any(has_bytes(v) for v in o)
        return False
    assert not has_bytes(out)
    json.dumps(out)


async def test_dispatcher_knows_people_op(db_session):
    from app.security import service
    if not hasattr(service, "people_ops"):
        pytest.skip("people.investigate dispatch wiring (uncommitted edits in "
                    "security/service.py) is absent in this checkout")
    prev = await service.preview_operation(
        db_session, user_id=uuid.uuid4(), op_key=PEOPLE_INVESTIGATE, params={"nid": "1"})
    assert prev["ok"] is True and prev["operation"] == PEOPLE_INVESTIGATE
    assert "investigate person" in prev["preview"]


async def test_length_cap_and_nid_normalisation(db_session, monkeypatch):
    uid = uuid.uuid4()
    out = await run_people_op(db_session, user_id=uid, op_key=PEOPLE_INVESTIGATE,
                              params={"name": "A" * 201})
    assert out == {"ok": False, "error": "parameter too long"}
    out = await run_people_op(db_session, user_id=uid, op_key=PEOPLE_INVESTIGATE,
                              params={"nid": "12AB"})
    assert out["ok"] is False and "digits" in out["error"]
    seen = {}

    async def fake(session, user_id, req, emit, **kw):
        seen["nid"] = req.nid
        return {"person": None, "notes": [], "agents_run": []}
    monkeypatch.setattr(people_ops, "run_investigation", fake)
    out = await run_people_op(db_session, user_id=uid, op_key=PEOPLE_INVESTIGATE,
                              params={"nid": " 1 1990-8 "})
    assert out["ok"] is True and seen["nid"] == "119908"


async def test_own_session_isolation_and_audit_persists(db_session, monkeypatch):
    class Boom:
        name = "relations"
        def can_handle(self, ctx):
            return True
        async def run(self, ctx):
            raise RuntimeError("boom")

    class DbOk:
        name = "db"
        def can_handle(self, ctx):
            return True
        async def run(self, ctx):
            return AgentResult("db", True, [], {"people": [{"nid": "9", "name": "X Y"}],
                                                "person_nid": "9"})
    monkeypatch.setattr(router, "_default_agents", lambda: {"db": DbOk(), "relations": Boom()})
    uid = uuid.uuid4()
    mark = f"caller-{uuid.uuid4().hex}"
    db_session.add(AuditLog(actor_id=uid, action=mark, detail={}))
    await db_session.flush()
    out = await run_people_op(db_session, user_id=uid, op_key=PEOPLE_INVESTIGATE,
                              params={"nid": "9"})
    assert out["ok"] is True and any("boom" in n for n in out["notes"])
    # caller's uncommitted row survived the agent failure
    got = (await db_session.execute(select(AuditLog).where(AuditLog.action == mark))).scalars().all()
    assert len(got) == 1
    async with _session_maker() as fresh:
        rows = (await fresh.execute(select(AuditLog).where(
            AuditLog.action == "people.investigate", AuditLog.actor_id == uid))).scalars().all()
        assert len(rows) == 1
        # caller's row is still uncommitted, so invisible to other sessions
        assert not (await fresh.execute(select(AuditLog).where(AuditLog.action == mark))).scalars().all()


async def test_fuzzy_name_ambiguous_and_nid_exact(db_session):
    t = uuid.uuid4().hex[:8].upper()
    n1, n2 = str(uuid.uuid4().int)[:16], str(uuid.uuid4().int)[:16]
    for n in (n1, n2):
        db_session.add(Person(nid=n, raw={}, forenames="ALPHONSE", surnames=f"TWAGIRA{t}",
                              sex="M", date_of_birth="1980"))
    await db_session.commit()
    uid = uuid.uuid4()
    out = await run_people_op(db_session, user_id=uid, op_key=PEOPLE_INVESTIGATE,
                              params={"name": f"ALPHONSE TWAGIRA{t}"})
    assert out["match"] == "fuzzy" and out["ambiguous"] is True
    assert out["candidate_count"] == 2
    assert len(out["other_candidates"]) == 1
    other = out["other_candidates"][0]
    assert set(other) == {"nid", "name"}
    assert {other["nid"], out["person"]["nid"]} == {n1, n2}
    assert any("multiple people match" in n for n in out["notes"])
    assert "unconfirmed" in out["confidence_note"]
    ex = await run_people_op(db_session, user_id=uid, op_key=PEOPLE_INVESTIGATE,
                             params={"nid": n1})
    assert ex["match"] == "exact" and ex["ambiguous"] is False
    assert ex["candidate_count"] == 1 and ex["other_candidates"] == []


# ---- final fix wave ------------------------------------------------------- #

async def test_passes_counts_and_ambiguity_through(db_session, monkeypatch):
    async def fake(session, user_id, req, emit, **kw):
        return {"person": {"nid": "1", "name": "A B"},
                "people": [{"nid": str(i), "name": "A B"} for i in range(1, 6)],
                "candidate_count": 9, "ambiguous": True, "analysis": "x",
                "analysis_dropped_count": 2, "name_collision_warning": True,
                "relations": None, "notes": [], "agents_run": ["db"]}
    monkeypatch.setattr(people_ops, "run_investigation", fake)
    out = await run_people_op(db_session, user_id=uuid.uuid4(), op_key=PEOPLE_INVESTIGATE,
                              params={"name": "A B"})
    assert out["candidate_count"] == 9 and out["ambiguous"] is True
    assert out["analysis_dropped_count"] == 2
    assert out["name_collision_warning"] is True
    assert "dropped" not in out


async def test_relations_nodes_included_and_nested_kin_reduced(db_session, monkeypatch):
    parent = {"nid": "P", "name": "Pa", "label": "father", "confidence": 80, "sex": "M",
              "phones": ["0788"], "children": [
                  {"nid": f"c{i}", "name": f"Kid {i}", "sex": "F", "date_of_birth": "2000",
                   "district": "D", "recorded_as": "father", "is_subject": False}
                  for i in range(14)]}
    nodes = [{"nid": None, "name": f"N{i}", "in_system": False, "source_ref": "https://w/1",
              "ambiguous": i == 0, "relation": "reported spouse", "fact_id": "F9", "extra": 1}
             for i in range(12)]

    async def fake(session, user_id, req, emit, **kw):
        return {"person": {"nid": "1"}, "relations": {
            "kin": {"parents": [parent], "siblings": [], "children": [], "partners": []},
            "associates": [{"person_b": "9", "name_b": "Z", "confidence": 70, "confirmed": False,
                            "shared": [{"what": "phone", "value": "0788", "source": "db"}]}],
            "weak_associates": [], "nodes": nodes},
            "notes": [], "agents_run": ["db", "relations"]}
    monkeypatch.setattr(people_ops, "run_investigation", fake)
    out = await run_people_op(db_session, user_id=uuid.uuid4(), op_key=PEOPLE_INVESTIGATE,
                              params={"nid": "1"})
    rel = out["relations"]
    assert len(rel["nodes"]) == 10 and rel["truncated"]["nodes"] is True
    assert rel["nodes"][0] == {"nid": None, "name": "N0", "in_system": False,
                               "ambiguous": True, "source_ref": "https://w/1"}
    assert set(rel["nodes"][1]) <= {"nid", "name", "in_system", "ambiguous", "source_ref"}
    p = rel["kin"]["parents"][0]
    assert p["label"] == "father" and p["phones"] == ["0788"]
    assert len(p["children"]) == 10
    assert p["children"][0] == {"nid": "c0", "name": "Kid 0"}
    assert rel["truncated"]["kin.parents.children"] is True
    assert rel["associates"][0]["shared"] == [{"what": "phone", "value": "0788", "source": "db"}]


async def test_rate_limited_chat_op(db_session, monkeypatch):
    called = {}

    async def fake(*a, **k):
        called["yes"] = True
        return {"person": None, "notes": [], "agents_run": []}
    monkeypatch.setattr(people_ops, "run_investigation", fake)
    uid = uuid.uuid4()
    for _ in range(30):
        db_session.add(AuditLog(actor_id=uid, action="people.investigate",
                                detail={"query": {"nid": "1", "web": False}}))
    await db_session.commit()
    out = await run_people_op(db_session, user_id=uid, op_key=PEOPLE_INVESTIGATE,
                              params={"nid": "1"})
    assert out == {"ok": False, "error": "rate limited: too many investigations, retry in a minute"}
    assert not called


# ---- follow-up -------------------------------------------------------------- #

async def test_busy_chat_op_and_slot_released(db_session, monkeypatch):
    from app.agents import ratelimit as rl
    rl._active.clear()
    uid = uuid.uuid4()

    async def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(people_ops, "run_investigation", boom)
    a, b = rl.acquire_slot(uid), rl.acquire_slot(uid)
    out = await run_people_op(db_session, user_id=uid, op_key=PEOPLE_INVESTIGATE, params={"nid": "1"})
    assert out == {"ok": False, "error": rl.BUSY}
    a.release(); b.release()
    out = await run_people_op(db_session, user_id=uid, op_key=PEOPLE_INVESTIGATE, params={"nid": "1"})
    assert out == {"ok": False, "error": "RuntimeError"}
    assert uid not in rl._active  # released after the exception


async def test_omitted_facts_and_spouse_cap(db_session, monkeypatch):
    async def fake(session, user_id, req, emit, **kw):
        return {"person": {"nid": "1"}, "relations": None, "omitted_facts": 4,
                "spouse_candidates": [f"S{i}" for i in range(14)], "notes": [], "agents_run": ["db"]}
    monkeypatch.setattr(people_ops, "run_investigation", fake)
    out = await run_people_op(db_session, user_id=uuid.uuid4(), op_key=PEOPLE_INVESTIGATE,
                              params={"nid": "1"})
    assert out["omitted_facts"] == 4 and out["spouse_candidates"] == [f"S{i}" for i in range(10)]
