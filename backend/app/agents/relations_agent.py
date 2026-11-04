"""relations_agent: kin (family.py + partner inference) and associates (shared facts)."""
from __future__ import annotations

import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.agents.base import AgentResult, Ctx, Fact
from app.agents.partners import infer_partners
from app.agents.shared_facts import (
    MIN_EDGE_CONFIDENCE,
    Edge,
    SharedFact,
    edge_confidence,
    find_db_edges,
    merge_edges,
)
from app.database.models.enrich import Person
from app.database.models.face import Face
from app.enrich import family

_WEB_SPOUSE_CONF = 40
_COWORKER_CAP = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.casefold().split())


def _node_key(nid: str | None, name: str) -> str:
    return f"nid:{nid}" if nid else f"name:{_norm(name)}"


class RelationsAgent:
    name = "relations"

    def can_handle(self, ctx: Ctx) -> bool:
        return ctx.person is not None

    async def run(self, ctx: Ctx) -> AgentResult:
        facts: list[Fact] = []
        data: dict = {
            "kin": {"partners": [], "parents": [], "children": [], "siblings": [], "extended": []},
            "associates": [], "weak_associates": [], "nodes": [],
        }
        try:
            await self._run(ctx, facts, data)
        except Exception as e:  # never raised to the router
            return AgentResult(agent=self.name, ok=False, facts=facts, data=data, error=str(e))
        return AgentResult(agent=self.name, ok=True, facts=facts, data=data)

    async def _run(self, ctx: Ctx, facts: list[Fact], data: dict) -> None:
        person = ctx.person
        session = ctx.session
        now = _now()
        nodes: dict[str, dict] = {}

        def add_node(nid, name, in_system, source_ref, **extra) -> None:
            key = _node_key(nid, name)
            if key not in nodes:
                nodes[key] = {"nid": nid, "name": name, "in_system": in_system,
                              "source_ref": source_ref, **extra}
            elif nid and not nodes[key]["in_system"]:
                nodes[key].update(in_system=True)

        # ---- kin
        rel = await family.find_relatives(session, person)
        out = family.relatives_out(rel)
        kin = data["kin"]
        for group in ("parents", "siblings", "children"):
            kin[group] = out[group]
            for r in rel[group]:
                p = r["person"]
                add_node(p.nid, family.person_name(p), True, f"person:{p.nid}")
                facts.append(Fact("", r["relation"], family.person_name(p), "db",
                                  f"person:{p.nid}", now, min(100, int(r["confidence"]))))
        ext = await family.extended_family(session, person)
        kin["extended"] = family.extended_out(ext)
        for f in ext:
            p = f["person"]
            add_node(p.nid, family.person_name(p), True, f"person:{p.nid}")
        kin_by_nid = {r["person"].nid: r for g in ("parents", "siblings", "children") for r in rel[g]}

        # ---- partners (inferred from shared children only)
        for link in await infer_partners(session, person):
            ref = f"person:{link.children_nids[0]}"
            kids = ", ".join(link.children_nids)
            nid = link.partner.nid if link.partner else None
            entry = {"nid": nid, "name": link.partner_name, "confidence": link.confidence,
                     "children": list(link.children_nids), "ambiguous": link.ambiguous,
                     "in_system": nid is not None}
            kin["partners"].append(entry)
            facts.append(Fact("", "probable partner", f"{link.partner_name} (shared children: {kids})",
                              "inference", ref, now, link.confidence))
            if nid:
                add_node(nid, family.person_name(link.partner), True, ref)
            else:
                add_node(None, link.partner_name, False, ref, **({"ambiguous": True} if link.ambiguous else {}))

        # ---- web results (optional)
        web = ctx.results.get("web")
        web = web if web is not None and web.ok else None

        if web is not None:
            urls = {}
            for f in web.facts:
                if f.claim == "reported spouse":
                    urls.setdefault(f.value, f.source_ref)
            me = family.person_name(person)
            for sp in web.data.get("spouse_names", []):
                if family.same_name(sp, me):
                    continue
                url = urls.get(sp, "")
                facts.append(Fact("", "reported spouse", sp, "web", url, now, _WEB_SPOUSE_CONF))
                found = [p for p in await family._people_named(session, sp) if p.nid != person.nid]
                if len(found) == 1:
                    add_node(found[0].nid, family.person_name(found[0]), True, url)
                elif found:
                    add_node(None, sp, False, url, ambiguous=True)
                else:
                    add_node(None, sp, False, url)

        # ---- associates
        edges: list[Edge] = list(await find_db_edges(session, person))
        if web is not None:
            edges += await self._coworker_edges(session, person, web)
        edges = await self._resolve_web_only(session, person, edges)
        existing = {e.person_b for e in edges if e.person_b}
        for nid in existing & set(kin_by_nid):
            r = kin_by_nid[nid]
            edges.append(Edge(person.nid, nid, family.person_name(r["person"]), r["relation"],
                              [SharedFact("kin", r["label"], "db", f"person:{nid}", 2, 1_000_000)], 0))
        merged = [e for e in merge_edges(edges) if e.person_b != person.nid]
        for e in merged:
            if all(f.source == "web" for f in e.shared):
                e.confidence = min(e.confidence, _COWORKER_CAP)
        merged.sort(key=lambda e: -e.confidence)
        for e in merged:
            add_node(e.person_b, e.name_b, e.person_b is not None, None)
            d = asdict(e)
            key = "associates" if e.confidence >= MIN_EDGE_CONFIDENCE else "weak_associates"
            data[key].append(d)
        data["nodes"] = list(nodes.values())

    async def _coworker_edges(self, session, person: Person, web: AgentResult) -> list[Edge]:
        orgs: dict[str, tuple[str, str]] = {}
        for f in web.facts:
            if f.claim == "organisation" and _norm(f.value):
                orgs.setdefault(_norm(f.value), (f.value, f.source_ref))
        if not orgs:
            return []
        nid_col = Face.extra["nid"].astext
        rows = (await session.execute(
            select(nid_col, Face.extra).where(nid_col.is_not(None), nid_col != person.nid)
        )).all()
        total = int((await session.execute(select(func.count()).select_from(Person))).scalar() or 0)
        holders: dict[str, set[str]] = {}
        for nid, extra in rows:
            raw = (extra or {}).get("orgs") or []
            if isinstance(raw, str):
                raw = [raw]
            for o in raw:
                if _norm(str(o)) in orgs:
                    holders.setdefault(_norm(str(o)), set()).add(nid)
        names: dict[str, str] = {}
        allnids = {n for s in holders.values() for n in s}
        if allnids:
            for p in (await session.execute(select(Person).where(Person.nid.in_(allnids)))).scalars():
                names[p.nid] = family.person_name(p)
        edges = []
        for key, nids in holders.items():
            value, url = orgs[key]
            for nid in sorted(nids):
                sf = SharedFact("organisation", value, "web", url, len(nids) + 1, total)
                edges.append(Edge(person.nid, nid, names.get(nid, ""), "coworker", [sf],
                                  min(_COWORKER_CAP, edge_confidence([sf]))))
        return edges

    async def _resolve_web_only(self, session, person: Person, edges: list[Edge]) -> list[Edge]:
        me = family.person_name(person)
        out: list[Edge] = []
        for e in edges:
            if e.person_b is None:
                if family.same_name(e.name_b, me):
                    continue
                found = [p for p in await family._people_named(session, e.name_b) if p.nid != person.nid]
                if len(found) == 1:
                    e.person_b = found[0].nid
                    e.name_b = family.person_name(found[0])
            out.append(e)
        return out
