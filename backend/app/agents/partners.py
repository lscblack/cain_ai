"""Partner inference: a person's likely partners, from children who name both parents."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enrich import Person
from app.enrich import family


@dataclass
class PartnerLink:
    partner: Person | None
    partner_name: str
    children_nids: list[str] = field(default_factory=list)
    confidence: int = 40
    ambiguous: bool = False


async def infer_partners(session: AsyncSession, person: Person) -> list[PartnerLink]:
    """Group ``person``'s children by the other parent's recorded name and resolve
    each group against the database. Never returns ``person`` as their own partner."""
    groups: dict[frozenset[str], tuple[str, list[str]]] = {}
    for child, relation in await family.children_of(session, person):
        other = child.mother_names if relation == "father" else child.father_names
        toks = family.name_tokens(other)
        if len(toks) < family.MIN_NAME_TOKENS or family.same_name(other, family.person_name(person)):
            continue
        name, nids = groups.setdefault(toks, (other.strip(), []))
        if child.nid not in nids:
            nids.append(child.nid)

    links: list[PartnerLink] = []
    for name, nids in groups.values():
        candidates = [p for p in await family._people_named(session, name) if p.nid != person.nid]
        if len(candidates) == 1:
            conf = min(90, 60 + 10 * (len(nids) - 1))
            links.append(PartnerLink(candidates[0], name, nids, conf, False))
        elif candidates:
            links.append(PartnerLink(None, name, nids, 40, True))
        else:
            links.append(PartnerLink(None, name, nids, 40, False))
    links.sort(key=lambda l: (-l.confidence, l.partner_name))
    return links
