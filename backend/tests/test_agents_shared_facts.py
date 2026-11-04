import uuid

from app.agents.shared_facts import (
    MIN_EDGE_CONFIDENCE,
    Edge,
    SharedFact,
    edge_confidence,
    find_db_edges,
    merge_edges,
    rarity_score,
)
from app.database.models.enrich import ParcelOwnership, Person, PhoneNumber


def P(nid, **kw):
    return Person(nid=nid, raw={}, **kw)


def _tag():
    return uuid.uuid4().hex[:8].upper()


async def _seed(db, *rows):
    for r in rows:
        db.add(r)
    await db.commit()


async def _fillers(db, t, n=12):
    await _seed(db, *[P(f"f{i}{t}", forenames="FILL", surnames=f"ER{t}") for i in range(n)])


def SF(what="phone", value="x", count=2, total=1000):
    return SharedFact(what, value, "db", "ref", count, total)


def test_rarity_unique_high_common_low():
    assert rarity_score(2, 10000) >= 50
    assert rarity_score(3000, 10000) < 50


def test_rarity_edges():
    assert rarity_score(1, 1) == 0
    assert rarity_score(0, 100) == 0
    assert rarity_score(1, 1000) == 100
    assert rarity_score(1000, 1000) == 0


def test_edge_confidence_boost_and_cap():
    assert edge_confidence([]) == 0
    one = edge_confidence([SF(count=2, total=1000)])
    two = edge_confidence([SF(count=2, total=1000), SF("parcel", "u", 2, 1000)])
    assert two == one + 5
    many = [SF(str(i), "v", 1, 1000) for i in range(6)]
    assert edge_confidence(many) == 95


async def test_shared_phone_edge(db_session):
    t = _tag()
    a = P(f"a{t}", forenames="ANNE", surnames=f"A{t}")
    b = P(f"b{t}", forenames="BOB", surnames=f"B{t}")
    await _seed(db_session, a, b)
    await _fillers(db_session, t)
    await _seed(db_session, PhoneNumber(msisdn=f"0788{t}", nid=a.nid), PhoneNumber(msisdn=f"0788{t}", nid=b.nid))
    edges = await find_db_edges(db_session, a)
    assert len(edges) == 1
    e = edges[0]
    assert e.relation == "shared phone"
    assert e.person_b == b.nid and e.person_a == a.nid
    assert e.confidence >= MIN_EDGE_CONFIDENCE
    assert e.shared[0].count == 2


async def test_co_owned_parcel_edge(db_session):
    t = _tag()
    a = P(f"a{t}", forenames="ANNE", surnames=f"A{t}")
    b = P(f"b{t}", forenames="BOB", surnames=f"B{t}")
    c = P(f"c{t}", forenames="CAL", surnames=f"C{t}")
    await _seed(db_session, a, b, c)
    await _fillers(db_session, t)
    upi = f"1/02/{t}"
    await _seed(
        db_session,
        ParcelOwnership(upi=upi, owner_nid=a.nid, is_current=True),
        ParcelOwnership(upi=upi, owner_nid=b.nid, is_current=True),
        ParcelOwnership(upi=upi, owner_nid=c.nid, is_current=False, content_hash="old"),
    )
    edges = await find_db_edges(db_session, a)
    assert [e.person_b for e in edges] == [b.nid]
    assert edges[0].relation == "co-owned parcel"
    assert edges[0].confidence >= MIN_EDGE_CONFIDENCE


async def test_same_village_edge_is_weak_when_village_large(db_session):
    t = _tag()
    loc = dict(district=f"D{t}", cell=f"C{t}", village=f"V{t}")
    village = [P(f"v{i}{t}", forenames="V", surnames=f"P{i}{t}", **loc) for i in range(30)]
    elsewhere = [P(f"o{i}{t}", forenames="O", surnames=f"Q{i}{t}", district=f"D{t}",
                   cell=f"C{t}", village=f"W{i % 5}{t}") for i in range(70)]
    await _seed(db_session, *village, *elsewhere)
    edges = await find_db_edges(db_session, village[0])
    assert len(edges) == 29
    assert all(e.relation == "same village" for e in edges)
    assert all(e.confidence < MIN_EDGE_CONFIDENCE for e in edges)
    assert all(e.person_b != village[0].nid for e in edges)


async def test_no_self_edge_and_no_location_no_village_edge(db_session):
    t = _tag()
    a = P(f"a{t}", forenames="ANNE", surnames=f"A{t}")
    await _seed(db_session, a, PhoneNumber(msisdn=f"0722{t}", nid=a.nid))
    assert await find_db_edges(db_session, a) == []


def test_merge_edges_unions_and_drops_self():
    f1, f2 = SF("sibling", "s", 2, 1000), SF("coworker", "c", 2, 1000)
    e1 = Edge("A", "B", "Bob", "sibling", [f1], edge_confidence([f1]))
    e2 = Edge("A", "B", "BOB", "coworker", [f2, f1], 10)
    selfe = Edge("A", "A", "Anne", "sibling", [f1], 80)
    out = merge_edges([e1, e2, selfe])
    assert len(out) == 1
    assert out[0].person_b == "B"
    assert len(out[0].shared) == 2
    assert out[0].confidence == edge_confidence([f1, f2])


def test_merge_edges_keys_web_only_by_normalised_name():
    f = SF("coworker", "c", 1, 1000)
    e1 = Edge("A", None, "Jean  Pierre", "coworker", [f], 60)
    e2 = Edge("A", None, "jean pierre", "coworker", [f], 60)
    e3 = Edge("A", None, "Marie", "coworker", [f], 60)
    assert len(merge_edges([e1, e2, e3])) == 2


# ---- final fix wave ------------------------------------------------------- #

def test_village_only_edge_capped_below_min_confidence():
    # realistic district ratios that used to clear MIN_EDGE_CONFIDENCE
    for count, total in ((300, 300_000), (100, 300_000), (20, 1000), (5, 200), (60, 3000)):
        assert rarity_score(count, total) > 40  # would have been the edge score
        c = edge_confidence([SF("village", "d/c/v", count, total)])
        assert c <= 40 < MIN_EDGE_CONFIDENCE, (count, total, c)


def test_village_adds_bonus_but_is_never_the_max():
    phone = SF("phone", "p", 2, 1000)
    village = SF("village", "d/c/v", 5, 200)  # rarity 70
    weak_org = SharedFact("organisation", "o", "web", "u", 200, 1000)  # rarity ~23
    assert edge_confidence([phone, village]) == edge_confidence([phone]) + 5
    assert edge_confidence([weak_org, village]) == rarity_score(200, 1000) + 5
    assert edge_confidence([weak_org, village]) < MIN_EDGE_CONFIDENCE


async def test_all_shared_phones_kept_on_one_edge(db_session):
    t = _tag()
    a = P(f"a{t}", forenames="ANNE", surnames=f"A{t}")
    b = P(f"b{t}", forenames="BOB", surnames=f"B{t}")
    await _seed(db_session, a, b)
    await _fillers(db_session, t)
    await _seed(db_session,
                *[PhoneNumber(msisdn=f"07{k}{t}", nid=n) for k in ("1", "2") for n in (a.nid, b.nid)])
    edges = await find_db_edges(db_session, a)
    assert len(edges) == 1
    e = edges[0]
    assert sorted((f.what, f.value) for f in e.shared) == [("phone", f"071{t}"), ("phone", f"072{t}")]
    assert e.confidence == edge_confidence([e.shared[0]]) + 5


async def test_phone_holder_query_is_bounded_but_count_is_true(db_session, monkeypatch):
    from app.agents import shared_facts
    monkeypatch.setattr(shared_facts, "_HOLDER_LIMIT", 2)
    t = _tag()
    people = [P(f"h{i}{t}", forenames="H", surnames=f"H{i}{t}") for i in range(5)]
    await _seed(db_session, *people)
    await _seed(db_session, *[PhoneNumber(msisdn=f"0790{t}", nid=p.nid) for p in people])
    edges = await find_db_edges(db_session, people[0])
    # ORDER BY nid LIMIT 2 -> h0 (self, skipped) and h1
    assert [e.person_b for e in edges] == [people[1].nid]
    assert edges[0].shared[0].count == 5
