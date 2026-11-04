import uuid

from app.agents import web_agent as wa
from app.agents.base import AgentResult, Ctx, Request
from app.agents.db_agent import DbAgent
from app.agents.web_agent import WebAgent
from app.database.models.enrich import Person


def _tag():
    return uuid.uuid4().hex[:8].upper()


def _num():
    return str(uuid.uuid4().int)[:16]


async def _emit(*_a, **_k):
    return None


def mkctx(db, **req):
    return Ctx(session=db, user_id=uuid.uuid4(), request=Request(**req),
               person=None, results={}, emit=_emit)


async def test_db_agent_returns_card_and_sets_person(db_session):
    t = _tag()
    p = Person(nid=_num(), raw={}, forenames="JEAN", surnames=f"NZEYIMANA{t}",
               date_of_birth="1970", district="GASABO")
    db_session.add(p)
    await db_session.commit()
    ctx = mkctx(db_session, nid=p.nid)
    res = await DbAgent().run(ctx)
    assert res.ok and res.agent == "db"
    assert ctx.person is not None and ctx.person.nid == p.nid
    assert res.data["person_nid"] == p.nid
    claims = {f.claim for f in res.facts}
    assert "national id" in claims and "district" in claims
    assert all(f.source == "db" and f.source_ref == f"person:{p.nid}" and f.confidence == 90
               for f in res.facts)


async def test_db_agent_name_ambiguous(db_session):
    t = _tag()
    for i in range(2):
        db_session.add(Person(nid=_num(), raw={}, forenames="ZED", surnames=f"QUUX{t}"))
    await db_session.commit()
    ctx = mkctx(db_session, name=f"ZED QUUX{t}")
    res = await DbAgent().run(ctx)
    assert res.ok and res.data["ambiguous"] is True and len(res.data["people"]) == 2
    assert ctx.person is not None
    assert all(f.confidence == 70 for f in res.facts)


async def test_db_agent_not_found_is_ok_with_empty_people(db_session):
    ctx = mkctx(db_session, nid=_num())
    res = await DbAgent().run(ctx)
    assert res.ok and res.data["people"] == [] and res.data["person_nid"] is None
    assert res.facts == [] and ctx.person is None


def test_db_can_handle(db_session):
    a = DbAgent()
    assert a.can_handle(mkctx(None, nid="1"))
    assert not a.can_handle(mkctx(None, web=True))


def _patch_web(monkeypatch, dossier=None, search=None):
    async def fake_dossier(session, term, *, public=False, as_name=False):
        return dossier or {"faces": [], "pages": [], "titles": [], "orgs": [], "locations": []}

    async def fake_search(queries, **kw):
        return search or {}
    monkeypatch.setattr(wa, "gather_dossier", fake_dossier)
    monkeypatch.setattr(wa, "search_candidates_free", fake_search)
    monkeypatch.setattr(wa, "search_available", lambda: True)


async def test_web_agent_offline_degrades(db_session, monkeypatch):
    _patch_web(monkeypatch, dossier={
        "faces": [], "pages": [{"url": "https://a.example/p", "title": "Jean Nzeyimana", "description": ""}],
        "titles": [], "orgs": [], "locations": []})

    async def boom(queries, **kw):
        raise RuntimeError("offline")
    monkeypatch.setattr(wa, "search_candidates_free", boom)
    res = await WebAgent().run(mkctx(db_session, name="Jean Nzeyimana", web=True))
    assert res.ok is False and "offline" in res.error
    assert any(f.source_ref == "https://a.example/p" for f in res.facts)


async def test_web_agent_facts_carry_url(db_session, monkeypatch):
    _patch_web(monkeypatch, dossier={
        "faces": [{"face_id": "f1", "source_url": "https://f.example/x", "crop_url": "/c/f1",
                   "description": "face"}],
        "pages": [{"url": "https://a.example/p", "title": "Jean Nzeyimana", "description": "CEO"}],
        "titles": ["Director"], "orgs": ["Acme Ltd"], "locations": ["Kigali"]},
        search={"https://s.example/1": "Jean"})
    res = await WebAgent().run(mkctx(db_session, name="Jean Paul Nzeyimana", web=True))
    assert res.ok and res.facts
    for f in res.facts:
        assert f.source == "web" and f.source_ref.startswith("http") and f.confidence <= 40
    claims = {f.claim for f in res.facts}
    assert {"organisation", "title", "location", "page mention", "possible web mention"} <= claims
    assert "name_collision_warning" not in res.data


async def test_web_agent_spouse_names_from_page_text(db_session, monkeypatch):
    _patch_web(monkeypatch, dossier={
        "faces": [], "pages": [{"url": "https://a.example/p", "title": "Jean Nzeyimana",
                                 "description": "Jean Nzeyimana is married to Marie Uwase."}],
        "titles": [], "orgs": [], "locations": []})
    res = await WebAgent().run(mkctx(db_session, name="Jean Nzeyimana"))
    assert "Marie Uwase" in res.data["spouse_names"]
    sp = [f for f in res.facts if f.claim == "reported spouse"]
    assert sp and sp[0].source_ref == "https://a.example/p" and sp[0].confidence <= 40
    assert res.data["name_collision_warning"] is True


async def test_web_agent_can_handle_rules(db_session):
    a = WebAgent()
    assert a.can_handle(mkctx(None, web=True))
    assert not a.can_handle(mkctx(None, name="x"))
    c = mkctx(None, name="x")
    c.results["db"] = AgentResult(agent="db", ok=True, data={"people": []})
    assert a.can_handle(c)
    c.results["db"] = AgentResult(agent="db", ok=True, data={"people": [{"nid": "1"}]})
    assert not a.can_handle(c)


async def test_web_agent_no_name_is_empty_ok(db_session):
    res = await WebAgent().run(mkctx(db_session, web=True))
    assert res.ok and res.facts == []
