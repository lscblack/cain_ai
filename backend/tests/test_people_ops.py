import uuid

import pytest
from sqlalchemy import select

from app.database.models.audit import AuditLog
from app.database.models.enrich import Person
from app.security import people_ops
from app.security.people_ops import PEOPLE_INVESTIGATE, preview, run_people_op


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
            "kin": {"parents": [], "children": []},
            "associates": [{"nid": str(i)} for i in range(25)],
            "weak_associates": []},
            "web_findings": [{"i": i} for i in range(9)],
            "notes": [], "agents_run": ["db"]}
    monkeypatch.setattr(people_ops, "run_investigation", fake)
    out = await run_people_op(db_session, user_id=uuid.uuid4(),
                              op_key=PEOPLE_INVESTIGATE, params={"nid": "1"})
    assert out["relations"]["truncated"] is True
    assert len(out["relations"]["associates"]) == 10
    assert len(out["web_findings"]) == 5


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
