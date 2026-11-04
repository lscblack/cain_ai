import uuid
from datetime import datetime, timezone

from app.agents.base import AgentResult, Ctx, Fact, Request
from app.agents.relations_agent import RelationsAgent
from app.agents.shared_facts import MIN_EDGE_CONFIDENCE, Edge
from app.database.models.enrich import Person, PhoneNumber
from app.database.models.face import Face


def P(nid, **kw):
    return Person(nid=nid, raw={}, **kw)


def _tag():
    return uuid.uuid4().hex[:8].upper()


async def _seed(db, *rows):
    for r in rows:
        db.add(r)
    await db.commit()


async def _noemit(*a, **k):
    return None


def _ctx(db, person, web=None):
    results = {}
    if web is not None:
        results["web"] = web
    return Ctx(session=db, user_id=uuid.uuid4(), request=Request(nid=person.nid),
               person=person, results=results, emit=_noemit)


def _web(spouses=(), orgs=(), ok=True):
    now = datetime.now(timezone.utc).isoformat()
    facts = [Fact("", "reported spouse", s, "web", f"http://w.test/{i}", now, 30)
             for i, s in enumerate(spouses)]
    facts += [Fact("", "organisation", o, "web", "http://w.test/org", now, 40) for o in orgs]
    return AgentResult("web", ok, facts, {"findings": [], "spouse_names": list(spouses)})


def _face(nid, orgs):
    return Face(image_hash=uuid.uuid4().hex, model="m", model_version="1", embedding_dim=1,
                embedding=[0.0], extra={"nid": nid, "orgs": orgs})


async def _fillers(db, t, n=12):
    await _seed(db, *[P(f"f{i}{t}", forenames="FILL", surnames=f"ER{t}") for i in range(n)])


def _family(t, with_children=2):
    dad, mum = f"JEAN NZEYIMANA{t}", f"MARIE UWASE{t}"
    rows = [
        P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}", sex="M", date_of_birth="1970"),
        P(f"p{t}", forenames="MARIE", surnames=f"UWASE{t}", sex="F", date_of_birth="1972"),
    ] + [P(f"c{i}{t}", forenames="K", surnames="X", father_names=dad, mother_names=mum,
           date_of_birth="2000") for i in range(with_children)]
    return rows


async def test_kin_and_partner_present(db_session):
    t = _tag()
    rows = _family(t)
    await _seed(db_session, *rows)
    res = await RelationsAgent().run(_ctx(db_session, rows[0]))
    assert res.ok
    kin = res.data["kin"]
    assert {c["nid"] for c in kin["children"]} == {f"c0{t}", f"c1{t}"}
    assert [p["nid"] for p in kin["partners"]] == [f"p{t}"]
    pf = [f for f in res.facts if f.claim == "probable partner"]
    assert len(pf) == 1 and pf[0].source == "inference"
    assert pf[0].source_ref in (f"person:c0{t}", f"person:c1{t}")
    nids = [n["nid"] for n in res.data["nodes"]]
    assert f"p{t}" in nids and len(nids) == len(set(nids))


async def test_married_without_children_has_no_partner(db_session):
    t = _tag()
    s = P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}", sex="M", marital_status="MARRIED")
    p = P(f"p{t}", forenames="MARIE", surnames=f"UWASE{t}", sex="F", marital_status="MARRIED")
    await _seed(db_session, s, p)
    res = await RelationsAgent().run(_ctx(db_session, s))
    assert res.data["kin"]["partners"] == []
    assert not [f for f in res.facts if f.claim == "probable partner"]


async def test_weak_links_separated(db_session):
    t = _tag()
    s = P(f"s{t}", forenames="ANNE", surnames=f"A{t}", district=f"D{t}", cell=f"C{t}", village=f"V{t}")
    strong = P(f"b{t}", forenames="BOB", surnames=f"B{t}")
    weak = P(f"w{t}", forenames="WIL", surnames=f"W{t}", district=f"D{t}", cell=f"C{t}", village=f"V{t}")
    await _seed(db_session, s, strong, weak)
    await _fillers(db_session, t, 30)
    await _seed(db_session, PhoneNumber(msisdn=f"0788{t}", nid=s.nid),
                PhoneNumber(msisdn=f"0788{t}", nid=strong.nid))
    res = await RelationsAgent().run(_ctx(db_session, s))
    assert strong.nid in [e["person_b"] for e in res.data["associates"]]
    # F2: every derived associate edge is an inference, never "confirmed"
    assert all(e["confirmed"] is False
               for e in res.data["associates"] + res.data["weak_associates"])
    assert all(e["confidence"] >= MIN_EDGE_CONFIDENCE for e in res.data["associates"])
    assert all(e["confidence"] < MIN_EDGE_CONFIDENCE for e in res.data["weak_associates"])
    assert weak.nid in [e["person_b"] for e in res.data["weak_associates"]]


async def test_web_spouse_in_system_becomes_clickable_node(db_session):
    t = _tag()
    s = P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}")
    sp = P(f"sp{t}", forenames="GRACE", surnames=f"MUKAMANA{t}")
    await _seed(db_session, s, sp)
    res = await RelationsAgent().run(_ctx(db_session, s, _web([f"Grace Mukamana{t}"])))
    node = next(n for n in res.data["nodes"] if n["nid"] == sp.nid)
    assert node["in_system"] is True
    assert node["source_ref"] == "http://w.test/0" and node["relation"] == "reported spouse"
    # F9: the web agent owns the "reported spouse" fact; relations never re-emits it
    assert not [f for f in res.facts if f.claim == "reported spouse"]


async def test_web_only_spouse_is_marked_not_in_system(db_session):
    t = _tag()
    s = P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}")
    await _seed(db_session, s)
    res = await RelationsAgent().run(_ctx(db_session, s, _web([f"Zed Nobody{t}"])))
    node = next(n for n in res.data["nodes"] if n["name"] == f"Zed Nobody{t}")
    assert node["nid"] is None and node["in_system"] is False
    assert node["source_ref"] == "http://w.test/0"


async def test_ambiguous_web_spouse_not_linked(db_session):
    t = _tag()
    s = P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}")
    a = P(f"a{t}", forenames="GRACE", surnames=f"MUKAMANA{t}")
    b = P(f"b{t}", forenames="GRACE", surnames=f"MUKAMANA{t}")
    await _seed(db_session, s, a, b)
    res = await RelationsAgent().run(_ctx(db_session, s, _web([f"Grace Mukamana{t}"])))
    node = next(n for n in res.data["nodes"] if n["name"] == f"Grace Mukamana{t}")
    assert node["nid"] is None and node["in_system"] is False and node["ambiguous"] is True


async def test_web_spouse_equal_to_subject_dropped(db_session):
    t = _tag()
    s = P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}")
    await _seed(db_session, s)
    res = await RelationsAgent().run(_ctx(db_session, s, _web([f"Jean Nzeyimana{t}"])))
    assert not [f for f in res.facts if f.claim == "reported spouse"]
    assert all(n["nid"] != s.nid and n["name"].upper() != f"JEAN NZEYIMANA{t}" for n in res.data["nodes"])


async def test_coworker_edge_is_web_sourced_unconfirmed(db_session):
    t = _tag()
    s = P(f"s{t}", forenames="ANNE", surnames=f"A{t}")
    o = P(f"o{t}", forenames="OLI", surnames=f"O{t}")
    await _seed(db_session, s, o)
    await _fillers(db_session, t, 30)
    await _seed(db_session, _face(o.nid, [f"Académie Ltd {t}"]), _face(s.nid, [f"Académie Ltd {t}"]))
    res = await RelationsAgent().run(_ctx(db_session, s, _web(orgs=[f"academie ltd {t}"])))
    edges = res.data["associates"] + res.data["weak_associates"]
    e = next(e for e in edges if e["person_b"] == o.nid)
    assert e in res.data["associates"]
    assert e["relation"] == "coworker" and e["confidence"] == 60 and e["confirmed"] is False
    assert e["shared"][0]["source"] == "web" and e["shared"][0]["source_ref"] == "http://w.test/org"
    assert all(e["person_b"] != s.nid for e in edges)


def _sibs(t, vil_a, vil_b):
    kw = dict(father_names=f"PAUL KAMANZI{t}", mother_names=f"ROSE INGABIRE{t}")
    s = P(f"s{t}", forenames="ANNE", surnames=f"A{t}", date_of_birth="2000", **kw, **vil_a)
    sib = P(f"sib{t}", forenames="ABEL", surnames=f"A{t}", date_of_birth="2002", **kw, **vil_b)
    return s, sib


async def test_sibling_and_coworker_merge_into_one_edge(db_session):
    t = _tag()
    s, sib = _sibs(t, {}, {})
    await _seed(db_session, s, sib)
    await _fillers(db_session, t, 30)
    await _seed(db_session, _face(sib.nid, [f"Acme {t}"]))
    res = await RelationsAgent().run(_ctx(db_session, s, _web(orgs=[f"ACME {t}"])))
    assert [x["nid"] for x in res.data["kin"]["siblings"]] == [sib.nid]
    edges = [e for e in res.data["associates"] + res.data["weak_associates"] if e["person_b"] == sib.nid]
    assert len(edges) == 1
    e = edges[0]
    assert "sibling" in e["relation"] and "coworker" in e["relation"]
    assert not [f for f in e["shared"] if f["what"] == "kin"]
    assert [f["what"] for f in e["shared"]] == ["organisation"]
    assert e["confidence"] <= 60 and e["confirmed"] is False


async def test_sibling_sharing_only_common_village_stays_weak(db_session):
    t = _tag()
    place = dict(district=f"D{t}", cell=f"C{t}", village=f"V{t}")
    s, sib = _sibs(t, place, place)
    await _seed(db_session, s, sib, *[P(f"v{i}{t}", forenames="FILL", surnames=f"ER{t}", **place)
                                       for i in range(30)])
    res = await RelationsAgent().run(_ctx(db_session, s))
    assert not [e for e in res.data["associates"] if e["person_b"] == sib.nid]
    e = next(e for e in res.data["weak_associates"] if e["person_b"] == sib.nid)
    assert "sibling" in e["relation"] and "same village" in e["relation"]
    assert e["confidence"] < MIN_EDGE_CONFIDENCE
    assert not [f for f in e["shared"] if f["what"] == "kin"]


async def test_resolve_web_only_edges(db_session):
    t = _tag()
    s = P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}")
    one = P(f"o{t}", forenames="OLI", surnames=f"ONE{t}")
    d1 = P(f"d1{t}", forenames="DUP", surnames=f"LICATE{t}")
    d2 = P(f"d2{t}", forenames="DUP", surnames=f"LICATE{t}")
    await _seed(db_session, s, one, d1, d2)
    mk = lambda name: Edge(s.nid, None, name, "coworker", [], 0)
    out = await RelationsAgent()._resolve_web_only(
        db_session, s, [mk(f"Jean Nzeyimana{t}"), mk(f"Oli One{t}"), mk(f"Dup Licate{t}"), mk(f"No Body{t}")])
    assert [(e.person_b, e.name_b if e.person_b is None else e.name_b.upper()) for e in out] == [
        (one.nid, f"OLI ONE{t}"), (None, f"Dup Licate{t}"), (None, f"No Body{t}")]


async def test_runs_without_web_result(db_session):
    t = _tag()
    rows = _family(t)
    await _seed(db_session, *rows)
    for web in (None, _web(["X Y"], ok=False)):
        res = await RelationsAgent().run(_ctx(db_session, rows[0], web))
        assert res.ok and res.data["kin"]["partners"]
        assert not [f for f in res.facts if f.claim == "reported spouse"]


async def test_small_village_in_small_district_stays_weak(db_session):
    # F2: 5 villagers in a district of 200 has rarity ~70 inside the district,
    # but "same village" alone is capped below MIN_EDGE_CONFIDENCE.
    t = _tag()
    place = dict(district=f"D{t}", cell=f"C{t}", village=f"V{t}")
    s = P(f"s{t}", forenames="ANNE", surnames=f"A{t}", **place)
    villagers = [P(f"v{i}{t}", forenames="VIL", surnames=f"L{i}{t}", **place) for i in range(4)]
    others = [P(f"o{i}{t}", forenames="OTH", surnames=f"R{i}{t}", district=f"D{t}",
                cell=f"C{t}", village=f"W{i % 7}{t}") for i in range(195)]
    await _seed(db_session, s, *villagers, *others)
    res = await RelationsAgent().run(_ctx(db_session, s))
    assert res.data["associates"] == []
    weak = {e["person_b"]: e for e in res.data["weak_associates"]}
    assert set(weak) == {v.nid for v in villagers}
    for e in weak.values():
        assert e["confidence"] <= 40 and e["confirmed"] is False
        assert [f["what"] for f in e["shared"]] == ["village"]
