"""Rarity-weighted shared-facts engine: edges between people backed by DB facts.

A shared fact is only as strong as it is rare: a phone held by two people is
strong evidence of a link, a village shared by thousands is not.
"""
from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enrich import ParcelOwnership, Person, PhoneNumber

MIN_EDGE_CONFIDENCE = 50
_EXTRA_FACT_BONUS = 5
_CONFIDENCE_CAP = 95
_VILLAGE_NEIGHBOUR_LIMIT = 500  # bound the work for very large villages
_HOLDER_LIMIT = 200  # bound the holders listed per phone (the count stays exact)
# "Same village" is measured inside the district, so even large villages score
# 50-70 there; living in the same village is never, on its own, evidence of a
# link. A village-only edge is therefore capped below MIN_EDGE_CONFIDENCE.
_VILLAGE_ONLY_CAP = 40
_VILLAGE = "village"


@dataclass
class SharedFact:
    what: str
    value: str
    source: str
    source_ref: str
    count: int  # how many people hold this value
    total: int


@dataclass
class Edge:
    person_a: str
    person_b: str | None
    name_b: str
    relation: str
    shared: list[SharedFact] = field(default_factory=list)
    confidence: int = 0


def rarity_score(count: int, total: int) -> int:
    """0-100; 100 = unique, ~0 = ubiquitous."""
    if total <= 1 or count <= 0:
        return 0
    ratio = min(count, total) / total
    score = round(100 * -math.log(ratio) / math.log(total))
    return max(0, min(100, score))


def edge_confidence(shared: list[SharedFact]) -> int:
    """Rarity of the strongest shared fact, +5 per extra independent fact.

    A "village" fact is never the strongest fact when any other fact is
    shared (it only adds the +5 bonus), and a village-only edge is capped at
    ``_VILLAGE_ONLY_CAP`` so it always stays a weak link.
    """
    if not shared:
        return 0
    strong = [f for f in shared if f.what != _VILLAGE]
    bonus = _EXTRA_FACT_BONUS * (len(shared) - 1)
    if not strong:
        best = max(rarity_score(f.count, f.total) for f in shared)
        return min(_VILLAGE_ONLY_CAP, best + bonus)
    best = max(rarity_score(f.count, f.total) for f in strong)
    return min(_CONFIDENCE_CAP, best + bonus)


def _full_name(p: Person) -> str:
    return " ".join(x for x in (p.forenames, p.surnames) if x).strip()


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.casefold().split())


_RELATION_ORDER = ["shared phone", "co-owned parcel", "same village"]


async def _scalar(session: AsyncSession, stmt) -> int:
    return int((await session.execute(stmt)).scalar() or 0)


async def find_db_edges(session: AsyncSession, person: Person) -> list[Edge]:
    """All DB-backed edges for ``person`` (weak ones included; callers filter)."""
    me = person.nid
    total = await _scalar(session, select(func.count()).select_from(Person))
    # other nid -> {relation: [SharedFact, ...]} -- ALL shared facts are kept
    # (deduped by what/value), so an edge states exactly what is shared
    found: dict[str, dict[str, list[SharedFact]]] = {}

    def add(nid: str, relation: str, fact: SharedFact) -> None:
        if nid and nid != me:
            facts = found.setdefault(nid, {}).setdefault(relation, [])
            if all((f.what, f.value) != (fact.what, fact.value) for f in facts):
                facts.append(fact)

    # shared phone
    mine = (await session.execute(
        select(distinct(PhoneNumber.msisdn)).where(PhoneNumber.nid == me)
    )).scalars().all()
    for msisdn in mine:
        holder_filter = (PhoneNumber.msisdn == msisdn, PhoneNumber.nid.is_not(None))
        count = await _scalar(session, select(func.count(distinct(PhoneNumber.nid)))
                              .where(*holder_filter))
        holders = (await session.execute(
            select(distinct(PhoneNumber.nid)).where(*holder_filter)
            .order_by(PhoneNumber.nid).limit(_HOLDER_LIMIT)
        )).scalars().all()
        fact = SharedFact("phone", msisdn, "db", f"enrich_phones:{msisdn}", count, total)
        for nid in holders:
            add(nid, "shared phone", fact)

    # co-owned parcel (current owners)
    upis = (await session.execute(
        select(distinct(ParcelOwnership.upi)).where(
            ParcelOwnership.owner_nid == me, ParcelOwnership.is_current.is_(True))
    )).scalars().all()
    for upi in upis:
        owners = (await session.execute(
            select(distinct(ParcelOwnership.owner_nid)).where(
                ParcelOwnership.upi == upi, ParcelOwnership.is_current.is_(True),
                ParcelOwnership.owner_nid.is_not(None))
        )).scalars().all()
        fact = SharedFact("parcel", upi, "db", f"enrich_parcel_ownership:{upi}", len(owners), total)
        for nid in owners:
            add(nid, "co-owned parcel", fact)

    # same district + cell + village; rarity measured within the district
    if person.district and person.cell and person.village:
        same = (Person.district == person.district, Person.cell == person.cell,
                Person.village == person.village)
        count = await _scalar(session, select(func.count()).select_from(Person).where(*same))
        district_total = await _scalar(
            session, select(func.count()).select_from(Person).where(Person.district == person.district))
        value = f"{person.district}/{person.cell}/{person.village}"
        fact = SharedFact("village", value, "db", f"enrich_persons:{value}", count, district_total)
        neighbours = (await session.execute(
            select(Person.nid).where(*same, Person.nid != me).limit(_VILLAGE_NEIGHBOUR_LIMIT)
        )).scalars().all()
        for nid in neighbours:
            add(nid, "same village", fact)

    if not found:
        return []
    people = {
        p.nid: p for p in (await session.execute(
            select(Person).where(Person.nid.in_(list(found)))
        )).scalars().all()
    }
    edges: list[Edge] = []
    for nid, rels in found.items():
        shared = [f for r in _RELATION_ORDER for f in rels.get(r, [])]
        best = {r: max(rarity_score(f.count, f.total) for f in rels[r]) for r in rels}
        # the label names the strongest NON-village relation when there is one
        ranked = [r for r in _RELATION_ORDER if r in rels and r != "same village"] or ["same village"]
        relation = max(ranked, key=lambda r: best[r])
        other = people.get(nid)
        edges.append(Edge(me, nid, _full_name(other) if other else "", relation,
                          shared, edge_confidence(shared)))
    edges.sort(key=lambda e: -e.confidence)
    return edges


def merge_edges(edges: list[Edge]) -> list[Edge]:
    """One edge per other person; shared facts unioned; self-links dropped."""
    merged: dict[str, Edge] = {}
    for e in edges:
        if e.person_b is not None and e.person_b == e.person_a:
            continue
        key = ("nid:" + e.person_b) if e.person_b else ("name:" + _norm(e.name_b))
        cur = merged.get(key)
        if cur is None:
            merged[key] = Edge(e.person_a, e.person_b, e.name_b, e.relation, [], 0)
            cur = merged[key]
        elif e.relation not in cur.relation.split(" + "):
            cur.relation += " + " + e.relation
        seen = {(f.what, f.value, f.source_ref) for f in cur.shared}
        for f in e.shared:
            k = (f.what, f.value, f.source_ref)
            if k not in seen:
                seen.add(k)
                cur.shared.append(f)
    for e in merged.values():
        e.confidence = edge_confidence(e.shared)
    return list(merged.values())
