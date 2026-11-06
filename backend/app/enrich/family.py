"""Family relationships derived from the saved citizen records.

Everything is inferred from data already in ``enrich_persons``:

* **Siblings** — two people whose ``father_names`` and/or ``mother_names`` match.
  Both parents match AND same district + cell + village  → 100 % sibling.
  Both parents match, location differs                    → 90 %.
  One parent matches AND same district + cell + village   → 75 % (likely).
  One parent matches                                      → 55 % (possible / half).
* **Parents** — people whose own full name equals this person's father/mother name.
* **Children** — the inverse of the above.

Names are compared as an unordered set of upper-cased tokens (so "JEAN PAUL
NZEYIMANA" == "NZEYIMANA JEAN PAUL"). A parent name with fewer than two tokens is
too generic to relate people and is ignored. These are *inferences*, never
confirmed kinship; every edge carries its confidence and the reasons behind it.
"""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enrich import Person

MIN_NAME_TOKENS = 2


# ───────────────────────── pure helpers ─────────────────────────────────── #
def name_tokens(value: str | None) -> frozenset[str]:
    """Accent/case-insensitive token set of a name."""
    if not value:
        return frozenset()
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return frozenset(t for t in re.split(r"[^A-Za-z0-9]+", text.upper()) if t)


def same_name(a: str | None, b: str | None) -> bool:
    ta, tb = name_tokens(a), name_tokens(b)
    return len(ta) >= MIN_NAME_TOKENS and ta == tb


def _norm(v: str | None) -> str:
    return " ".join(sorted(name_tokens(v)))


def same_place(a: Person, b: Person) -> bool:
    """District + cell + village all present and equal."""
    pairs = ((a.district, b.district), (a.cell, b.cell), (a.village, b.village))
    return all(x and y and _norm(x) == _norm(y) for x, y in pairs)


def birth_year(p: Person) -> int | None:
    m = re.search(r"(1[89]\d\d|20\d\d)", p.date_of_birth or "")
    return int(m.group(1)) if m else None


def _sex(p: Person) -> str | None:
    s = (p.sex or "").strip().upper()
    return s[:1] if s[:1] in ("M", "F") else None


def sibling_score(a: Person, b: Person) -> tuple[int, str, list[str]] | None:
    """Return (confidence %, label, reasons) if ``a`` and ``b`` look like siblings."""
    if a.nid == b.nid:
        return None
    father = same_name(a.father_names, b.father_names)
    mother = same_name(a.mother_names, b.mother_names)
    if not (father or mother):
        return None
    place = same_place(a, b)
    reasons = []
    if father:
        reasons.append("same father")
    if mother:
        reasons.append("same mother")
    if place:
        reasons.append("same district, cell and village")
    if father and mother:
        return (100, "sibling", reasons) if place else (90, "sibling", reasons)
    if place:
        return 75, "likely sibling", reasons
    return 55, "possible sibling (half?)", reasons


def parent_score(child: Person, cand: Person, relation: str) -> tuple[int, list[str]] | None:
    """Confidence that ``cand`` is ``child``'s ``relation`` ('father'|'mother')."""
    want = "M" if relation == "father" else "F"
    s = _sex(cand)
    if s and s != want:
        return None
    cy, py = birth_year(child), birth_year(cand)
    if cy and py and cy - py < 12:
        return None  # implausible age gap
    reasons = [f"name matches recorded {relation}"]
    score = 65
    if s == want:
        score += 10
        reasons.append("sex consistent")
    if cand.district and _norm(cand.district) == _norm(child.district):
        score += 10
        reasons.append("same district")
    if cy and py:
        score += 5
        reasons.append("plausible age gap")
    return min(score, 95), reasons


# ───────────────────────── DB queries ───────────────────────────────────── #
_ACCENTED = "ÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝŸ"
_PLAIN = "AAAAAACEEEEIIIINOOOOOOUUUUYY"


def fold(col):
    """SQL: upper-case + strip common Latin accents, matching :func:`name_tokens`
    (so 'Éric' in the DB is found by a search for 'eric')."""
    return func.translate(func.upper(col), _ACCENTED, _PLAIN)


def _full_name_col():
    return fold(func.concat_ws(" ", Person.forenames, Person.surnames))


async def _people_named(session: AsyncSession, name: str | None, *, limit: int = 40) -> list[Person]:
    toks = name_tokens(name)
    if len(toks) < MIN_NAME_TOKENS:
        return []
    rows = (
        await session.execute(
            select(Person).where(and_(*[_full_name_col().like(f"%{t}%") for t in toks])).limit(limit)
        )
    ).scalars().all()
    return [p for p in rows if name_tokens(f"{p.forenames or ''} {p.surnames or ''}") == toks]


async def _people_with_parent(session: AsyncSession, col, name: str | None, *, limit: int = 200) -> list[Person]:
    toks = name_tokens(name)
    if len(toks) < MIN_NAME_TOKENS:
        return []
    rows = (
        await session.execute(
            select(Person).where(and_(*[fold(col).like(f"%{t}%") for t in toks])).limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def children_of(session: AsyncSession, parent: Person) -> list[tuple[Person, str]]:
    """Everyone whose recorded father/mother name is ``parent``'s name, with an
    age-plausible gap. Returns ``(child, 'father'|'mother')`` pairs."""
    name = person_name(parent)
    out: dict[str, tuple[Person, str]] = {}
    for relation, col, allowed in (("father", Person.father_names, _sex(parent) != "F"),
                                   ("mother", Person.mother_names, _sex(parent) != "M")):
        if not allowed:
            continue
        for cand in await _people_with_parent(session, col, name):
            recorded = cand.father_names if relation == "father" else cand.mother_names
            if (cand.nid != parent.nid and same_name(recorded, name)
                    and parent_score(cand, parent, relation)):
                out.setdefault(cand.nid, (cand, relation))
    return list(out.values())


async def _phones(session: AsyncSession, nid: str) -> list[str]:
    from app.database.models.enrich import PhoneNumber

    rows = (await session.execute(
        select(PhoneNumber.msisdn).where(PhoneNumber.nid == nid))).scalars().all()
    return list(dict.fromkeys(rows))


def person_name(p: Person) -> str:
    return " ".join(x for x in (p.forenames, p.surnames) if x).strip() or p.nid


async def find_relatives(session: AsyncSession, person: Person, *, detail: bool = True) -> dict:
    """Parents, siblings and children of ``person`` found in the saved database.

    Returns ``{"parents": [...], "siblings": [...], "children": [...]}`` where each
    entry is ``{"person": Person, "relation", "label", "confidence", "reasons"}``.
    """
    parents: list[dict] = []
    for relation, pname in (("father", person.father_names), ("mother", person.mother_names)):
        found = []
        for cand in await _people_named(session, pname):
            if cand.nid == person.nid:
                continue
            sc = parent_score(person, cand, relation)
            if sc:
                found.append({"person": cand, "relation": relation, "label": relation,
                              "confidence": sc[0], "reasons": sc[1]})
        found.sort(key=lambda r: -r["confidence"])
        parents.extend(found[:3])

    siblings: dict[str, dict] = {}
    for col, pname in ((Person.father_names, person.father_names),
                       (Person.mother_names, person.mother_names)):
        for cand in await _people_with_parent(session, col, pname):
            sc = sibling_score(person, cand)
            if sc and (cand.nid not in siblings or siblings[cand.nid]["confidence"] < sc[0]):
                siblings[cand.nid] = {"person": cand, "relation": "sibling", "label": sc[1],
                                      "confidence": sc[0], "reasons": sc[2]}

    children = {c.nid: {"person": c, "relation": "child", "label": "child",
                        "confidence": 70, "reasons": [f"recorded {how} name matches"]}
                for c, how in await children_of(session, person)}

    # For every parent found in the DB: everyone recorded as their child (the
    # person's full and half siblings through that parent, plus the person).
    for r in (parents if detail else []):
        r["children"] = [
            {"person": c, "how": how, "is_subject": c.nid == person.nid}
            for c, how in await children_of(session, r["person"])
        ]
        r["phones"] = await _phones(session, r["person"].nid)

    return {
        "parents": parents,
        "siblings": sorted(siblings.values(), key=lambda r: -r["confidence"]),
        "children": sorted(children.values(), key=lambda r: -r["confidence"]),
    }


def mini(p: Person) -> dict:
    """Compact card for a relative."""
    from app.intelligence.face.crops import has_crop

    fid = str(p.photo_face_id) if p.photo_face_id else None
    return {
        "nid": p.nid, "name": person_name(p), "sex": p.sex, "date_of_birth": p.date_of_birth,
        "district": p.district, "sector": p.sector, "cell": p.cell, "village": p.village,
        "province": p.province, "father_names": p.father_names, "mother_names": p.mother_names,
        "nationality": p.nationality, "place_of_birth": p.place_of_birth,
        "marital_status": p.marital_status, "document_number": p.document_number,
        "photo_url": f"/intelligence/face/crop/{fid}" if fid and has_crop(fid) else None,
    }


def _rel_out(r: dict) -> dict:
    out = {**mini(r["person"]), "relation": r["relation"], "label": r["label"],
           "confidence": r["confidence"], "reasons": r["reasons"]}
    if "children" in r:  # a parent found in the DB: their details + all their children
        out["phones"] = r.get("phones", [])
        out["children"] = [{**mini(c["person"]), "recorded_as": c["how"], "is_subject": c["is_subject"]}
                           for c in r["children"]]
    return out


def relatives_out(rel: dict) -> dict:
    """JSON-safe version of :func:`find_relatives`."""
    return {group: [_rel_out(r) for r in rel[group]] for group in ("parents", "siblings", "children")}


def build_tree(person: Person, rel: dict) -> dict:
    """Nodes + edges for a family-tree view centred on ``person``."""
    nodes = {person.nid: {**mini(person), "focus": True}}
    edges: list[dict] = []
    for r in rel["parents"]:
        p = r["person"]
        nodes.setdefault(p.nid, mini(p))
        edges.append({"from": p.nid, "to": person.nid, "type": "parent_of",
                      "label": r["relation"], "confidence": r["confidence"]})
        for c in r.get("children", []):
            if not c["is_subject"]:
                nodes.setdefault(c["person"].nid, mini(c["person"]))
                edges.append({"from": p.nid, "to": c["person"].nid, "type": "parent_of",
                              "label": c["how"], "confidence": 70})
    for r in rel["siblings"]:
        p = r["person"]
        nodes.setdefault(p.nid, mini(p))
        edges.append({"from": person.nid, "to": p.nid, "type": "sibling_of",
                      "label": r["label"], "confidence": r["confidence"]})
    for r in rel["children"]:
        p = r["person"]
        nodes.setdefault(p.nid, mini(p))
        edges.append({"from": person.nid, "to": p.nid, "type": "parent_of",
                      "label": "child", "confidence": r["confidence"]})
    return {"nodes": list(nodes.values()), "edges": edges}


def add_extended_to_tree(tree: dict, found: list[dict]) -> dict:
    have = {n["nid"] for n in tree["nodes"]}
    for f in found:
        if f["person"].nid not in have:
            tree["nodes"].append({**mini(f["person"]), "label": f["label"]})
            have.add(f["person"].nid)
    return tree


# ───────────────────────── extended family (graph walk) ─────────────────── #
# Each hop is "up" (to a parent), "side" (to a sibling) or "down" (to a child).
# A path is simplified with kinship identities, then named:
#   up·down → side (a parent's child is a sibling)   side·side → side
#   side·up → up   (a sibling's parent is a parent)  down·side → down
_RULES = {("up", "down"): ("side",), ("side", "side"): ("side",),
          ("side", "up"): ("up",), ("down", "side"): ("down",)}

_NAMES: dict[tuple, tuple[str, str, str]] = {   # path -> (male, female, neutral)
    ("up",): ("father", "mother", "parent"),
    ("side",): ("brother", "sister", "sibling"),
    ("down",): ("son", "daughter", "child"),
    ("up", "up"): ("grandfather", "grandmother", "grandparent"),
    ("up", "up", "up"): ("great-grandfather", "great-grandmother", "great-grandparent"),
    ("down", "down"): ("grandson", "granddaughter", "grandchild"),
    ("up", "side"): ("uncle", "aunt", "uncle/aunt"),
    ("up", "up", "side"): ("great-uncle", "great-aunt", "great-uncle/aunt"),
    ("up", "side", "down"): ("cousin", "cousin", "cousin"),
    ("up", "up", "side", "down"): ("first cousin once removed", "first cousin once removed",
                                   "first cousin once removed"),
    ("up", "side", "down", "down"): ("cousin's son", "cousin's daughter", "cousin's child"),
    ("side", "down"): ("nephew", "niece", "nephew/niece"),
    ("side", "down", "down"): ("grandnephew", "grandniece", "grandnephew/niece"),
    ("down", "up"): ("co-parent (shared child)", "co-parent (shared child)", "co-parent (shared child)"),
}
DIRECT = {("up",), ("side",), ("down",)}


def simplify(path: tuple[str, ...]) -> tuple[str, ...]:
    """Reduce a hop path with the kinship identities in ``_RULES``."""
    out: list[str] = []
    for step in path:
        out.append(step)
        while len(out) >= 2 and (out[-2], out[-1]) in _RULES:
            repl = _RULES[(out[-2], out[-1])]
            out[-2:] = list(repl)
    return tuple(out)


def kin_label(path: tuple[str, ...], sex: str | None) -> str:
    names = _NAMES.get(path)
    if not names:
        return f"relative ({len(path)} steps)"
    s = (sex or "").strip().upper()[:1]
    return names[0] if s == "M" else names[1] if s == "F" else names[2]


async def extended_family(
    session: AsyncSession, person: Person, *, max_hops: int = 4, max_people: int = 60,
) -> list[dict]:
    """Walk parent/sibling/child links outward from ``person`` (breadth-first,
    shortest path wins) and name everyone reached: grandparents, uncles/aunts,
    cousins, nephews/nieces, … Confidence multiplies along the path. Direct
    parents/siblings/children are excluded (they are listed separately)."""
    seen: dict[str, dict] = {person.nid: {"path": (), "conf": 100.0}}
    frontier: list[tuple[Person, tuple[str, ...], float, list[str]]] = [(person, (), 100.0, [])]
    found: list[dict] = []
    for _hop in range(max_hops):
        nxt = []
        for node, path, conf, via in frontier:
            rel = await find_relatives(session, node, detail=False)
            for group, step in (("parents", "up"), ("siblings", "side"), ("children", "down")):
                for r in rel[group]:
                    other: Person = r["person"]
                    if other.nid in seen:
                        continue
                    raw = path + (step,)
                    short = simplify(raw)
                    if not short:            # walked back to the subject
                        continue
                    c = conf * r["confidence"] / 100.0
                    seen[other.nid] = {"path": short, "conf": c}
                    chain = via + [person_name(node)] if node.nid != person.nid else via
                    if short not in DIRECT:
                        found.append({"person": other, "path": list(short),
                                      "label": kin_label(short, other.sex),
                                      "confidence": round(c), "via": chain})
                    nxt.append((other, short, c, chain))
                    if len(seen) > max_people:
                        break
        frontier = nxt
        if not frontier or len(seen) > max_people:
            break
    found.sort(key=lambda f: (len(f["path"]), -f["confidence"]))
    return found


def extended_out(found: list[dict]) -> list[dict]:
    return [{**mini(f["person"]), "relation": "extended", "label": f["label"], "path": f["path"],
             "confidence": f["confidence"], "via": f["via"],
             "reasons": [" → ".join(f["path"])] + ([f"via {', '.join(f['via'])}"] if f["via"] else [])}
            for f in found]
