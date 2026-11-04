import uuid

from app.agents.partners import infer_partners
from app.database.models.enrich import Person


def P(nid, **kw):
    return Person(nid=nid, raw={}, **kw)


def _tag():
    return uuid.uuid4().hex[:8].upper()


async def _seed(db, *people):
    for p in people:
        db.add(p)
    await db.commit()


async def test_partner_from_two_shared_children(db_session):
    t = _tag()
    dad, mum = f"JEAN NZEYIMANA{t}", f"MARIE UWASE{t}"
    subject = P(f"s{t}", forenames=f"JEAN", surnames=f"NZEYIMANA{t}", sex="M", date_of_birth="1970")
    partner = P(f"p{t}", forenames="MARIE", surnames=f"UWASE{t}", sex="F", date_of_birth="1972")
    c1 = P(f"c1{t}", forenames="A", surnames="X", father_names=dad, mother_names=mum, date_of_birth="2000")
    c2 = P(f"c2{t}", forenames="B", surnames="X", father_names=dad, mother_names=mum, date_of_birth="2003")
    await _seed(db_session, subject, partner, c1, c2)
    links = await infer_partners(db_session, subject)
    assert len(links) == 1
    link = links[0]
    assert link.partner.nid == partner.nid
    assert sorted(link.children_nids) == sorted([c1.nid, c2.nid])
    assert link.confidence >= 70
    assert link.ambiguous is False


async def test_one_child_lower_confidence_than_two(db_session):
    t1, t2 = _tag(), _tag()

    async def build(t, n):
        dad, mum = f"JEAN NZEYIMANA{t}", f"MARIE UWASE{t}"
        rows = [
            P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}", sex="M", date_of_birth="1970"),
            P(f"p{t}", forenames="MARIE", surnames=f"UWASE{t}", sex="F", date_of_birth="1972"),
        ] + [P(f"c{i}{t}", forenames="K", surnames="X", father_names=dad, mother_names=mum,
               date_of_birth="2000") for i in range(n)]
        await _seed(db_session, *rows)
        return rows[0]

    one = await infer_partners(db_session, await build(t1, 1))
    two = await infer_partners(db_session, await build(t2, 2))
    assert one[0].confidence < two[0].confidence


async def test_no_children_no_partner(db_session):
    t = _tag()
    subject = P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}", sex="M", marital_status="MARRIED")
    await _seed(db_session, subject)
    assert await infer_partners(db_session, subject) == []


async def test_ambiguous_common_name(db_session):
    t = _tag()
    dad, mum = f"JEAN NZEYIMANA{t}", f"MARIE UWASE{t}"
    subject = P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}", sex="M", date_of_birth="1970")
    m1 = P(f"m1{t}", forenames="MARIE", surnames=f"UWASE{t}", sex="F")
    m2 = P(f"m2{t}", forenames="MARIE", surnames=f"UWASE{t}", sex="F")
    c1 = P(f"c1{t}", forenames="A", surnames="X", father_names=dad, mother_names=mum, date_of_birth="2000")
    await _seed(db_session, subject, m1, m2, c1)
    links = await infer_partners(db_session, subject)
    assert len(links) == 1
    assert links[0].partner is None
    assert links[0].ambiguous is True
    assert links[0].confidence <= 40


async def test_partner_never_subject(db_session):
    t = _tag()
    nm = f"JEAN NZEYIMANA{t}"
    subject = P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}", sex="M", date_of_birth="1970")
    c1 = P(f"c1{t}", forenames="A", surnames="X", father_names=nm, mother_names=nm, date_of_birth="2000")
    await _seed(db_session, subject, c1)
    links = await infer_partners(db_session, subject)
    assert all(l.partner is None or l.partner.nid != subject.nid for l in links)
    assert links == []


async def test_partner_name_not_in_db(db_session):
    t = _tag()
    dad, mum = f"JEAN NZEYIMANA{t}", f"MARIE UWASE{t}"
    subject = P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}", sex="M", date_of_birth="1970")
    c1 = P(f"c1{t}", forenames="A", surnames="X", father_names=dad, mother_names=mum, date_of_birth="2000")
    await _seed(db_session, subject, c1)
    links = await infer_partners(db_session, subject)
    assert len(links) == 1
    assert links[0].partner is None
    assert links[0].partner_name == mum
    assert links[0].ambiguous is False
    assert links[0].confidence == 40


# ---- F11: implausible partner age gap ------------------------------------- #

async def _partner_case(db_session, subject_dob, partner_dob):
    t = _tag()
    dad, mum = f"JEAN NZEYIMANA{t}", f"MARIE UWASE{t}"
    subject = P(f"s{t}", forenames="JEAN", surnames=f"NZEYIMANA{t}", sex="M", date_of_birth=subject_dob)
    partner = P(f"p{t}", forenames="MARIE", surnames=f"UWASE{t}", sex="F", date_of_birth=partner_dob)
    kids = [P(f"c{i}{t}", forenames="K", surnames="X", father_names=dad, mother_names=mum,
              date_of_birth="2000") for i in range(2)]
    await _seed(db_session, subject, partner, *kids)
    return subject, partner, await infer_partners(db_session, subject)


async def test_partner_with_49_year_gap_is_dropped(db_session):
    subject, partner, links = await _partner_case(db_session, "1950", "1999")
    assert all(l.partner is None or l.partner.nid != partner.nid for l in links)
    assert links and links[0].partner is None and links[0].confidence == 40


async def test_partner_with_10_year_gap_is_kept(db_session):
    subject, partner, links = await _partner_case(db_session, "1960", "15/03/1970")
    assert [l.partner.nid for l in links] == [partner.nid]


async def test_partner_with_unknown_birth_year_is_kept(db_session):
    subject, partner, links = await _partner_case(db_session, "1950", None)
    assert [l.partner.nid for l in links] == [partner.nid]
