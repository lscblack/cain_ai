"""DbAgent: resolve the subject from the saved identity database."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.base import AgentResult, Ctx, Fact
from app.database.models.enrich import Person
from app.enrich.lookup import resolve_identity

# card key -> claim wording
_FIELDS = [
    ("nid", "national id"),
    ("name", "name"),
    ("sex", "sex"),
    ("date_of_birth", "date of birth"),
    ("father_names", "father"),
    ("mother_names", "mother"),
    ("nationality", "nationality"),
    ("place_of_birth", "place of birth"),
    ("marital_status", "marital status"),
    ("province", "province"),
    ("district", "district"),
    ("sector", "sector"),
    ("cell", "cell"),
    ("village", "village"),
    ("document_number", "document number"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DbAgent:
    name = "db"

    def can_handle(self, ctx: Ctx) -> bool:
        r = ctx.request
        return bool(r.nid or r.phone or r.name or r.image)

    async def run(self, ctx: Ctx) -> AgentResult:
        r = ctx.request
        try:
            if r.nid:
                res = await resolve_identity(ctx.session, ctx.user_id, nid=r.nid)
                exact = True
            elif r.phone:
                res = await resolve_identity(ctx.session, ctx.user_id, phone=r.phone)
                exact = True
            elif r.name:
                res = await resolve_identity(ctx.session, ctx.user_id, name=r.name)
                exact = False
            else:  # image-only: nothing for the identity DB to key on
                return AgentResult(agent=self.name, ok=True,
                                   data={"people": [], "person_nid": None})
            if not res.get("ok", True):
                return AgentResult(agent=self.name, ok=False, error=str(res.get("error")),
                                   data={"people": [], "person_nid": None})
            cards = list(res.get("people") or []) if res.get("found") else []
            if not cards:
                return AgentResult(agent=self.name, ok=True,
                                   data={"people": [], "person_nid": None})
            top = cards[0]
            nid = top["nid"]
            conf = 90 if exact else 70
            ref = f"person:{nid}"
            now = _now()
            facts = [
                Fact(id="", claim=claim, value=str(top[key]), source="db",
                     source_ref=ref, retrieved_at=now, confidence=conf)
                for key, claim in _FIELDS if top.get(key)
            ]
            facts += [Fact(id="", claim="phone", value=str(p), source="db", source_ref=ref,
                           retrieved_at=now, confidence=conf) for p in top.get("phones") or []]
            facts += [Fact(id="", claim="land parcel", value=str(u), source="db", source_ref=ref,
                           retrieved_at=now, confidence=conf) for u in top.get("upis") or []]
            ctx.person = (await ctx.session.execute(
                select(Person).where(Person.nid == nid))).scalars().first()
            data = {"people": cards, "person_nid": nid}
            if not exact and len(cards) > 1:
                data["ambiguous"] = True
            return AgentResult(agent=self.name, ok=True, facts=facts, data=data)
        except Exception as e:  # never raise out of an agent
            return AgentResult(agent=self.name, ok=False, error=str(e),
                               data={"people": [], "person_nid": None})
