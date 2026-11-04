"""WebAgent: corpus dossier + free web search, URL-only (no page fetching)."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from app.agents.base import AgentResult, Ctx, Fact
from app.agents.web_text import extract_spouse_names
from app.discovery.dossier import gather_dossier
from app.discovery.search import search_available, search_candidates_free
from app.enrich.family import person_name

_NAME_ONLY_CONF = 40
_SEARCH_CONF = 30


def _fold(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in t if not unicodedata.combining(c)).casefold()


def _mentions(text: str, needle: str) -> bool:
    """Whole-word/phrase match on folded text ("actor" does not match "factory")."""
    toks = needle.split()
    if not toks:
        return False
    pat = r"(?<!\w)" + r"\s+".join(re.escape(t) for t in toks) + r"(?!\w)"
    return re.search(pat, text) is not None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WebAgent:
    name = "web"

    def can_handle(self, ctx: Ctx) -> bool:
        if ctx.request.web:
            return True
        db = ctx.results.get("db")
        return db is not None and not (db.data or {}).get("people")

    async def run(self, ctx: Ctx) -> AgentResult:
        name = person_name(ctx.person) if ctx.person is not None else (ctx.request.name or "")
        name = name.strip()
        if not name:
            return AgentResult(agent=self.name, ok=True, data={"findings": [], "spouse_names": []})

        facts: list[Fact] = []
        findings: list[dict] = []
        spouses: list[str] = []
        data: dict = {"findings": findings, "spouse_names": spouses}
        # web hits are name-only matches (never NID-confirmed), so always warn
        data["name_collision_warning"] = True
        now = _now()

        def add(claim: str, value: str, url: str, conf: int) -> None:
            facts.append(Fact(id="", claim=claim, value=value, source="web",
                              source_ref=url, retrieved_at=now, confidence=min(conf, 100)))

        try:
            dossier = await gather_dossier(ctx.session, name, as_name=True)
            urls: list[str] = []
            texts: list[tuple[str, str]] = []
            src_text: list[tuple[str, str]] = []  # (url, folded text) for provenance
            for pg in dossier.get("pages") or []:
                url = pg.get("url")
                if not url:
                    continue
                urls.append(url)
                title = pg.get("title") or url
                add("page mention", title, url, _NAME_ONLY_CONF)
                findings.append({"type": "page", "url": url, "title": pg.get("title")})
                ptxt = f"{pg.get('title') or ''}. {pg.get('description') or ''}"
                texts.append((url, ptxt))
                src_text.append((url, _fold(ptxt)))
            for fa in dossier.get("faces") or []:
                url = fa.get("source_url")
                if not url:
                    continue
                urls.append(url)
                add("face mention", fa.get("description") or "face match", url, _NAME_ONLY_CONF)
                findings.append({"type": "face", "url": url, "face_id": fa.get("face_id")})
                if fa.get("description"):
                    texts.append((url, fa["description"]))
                src_text.append((url, _fold(fa.get("description") or "")))
            # aggregated attributes: cite only sources whose text contains the value
            if urls:
                for key, claim in (("orgs", "organisation"), ("titles", "title"),
                                   ("locations", "location")):
                    for v in dossier.get(key) or []:
                        needle = _fold(str(v))
                        srcs = [u for u, t in src_text if _mentions(t, needle)]
                        srcs = list(dict.fromkeys(srcs))
                        if srcs:
                            add(claim, str(v), srcs[0], _NAME_ONLY_CONF)
                            findings.append({"type": claim, "value": v, "url": srcs[0],
                                             "sources": srcs})
                        else:
                            n = len(set(urls))
                            add(claim, f"{v} [aggregated across {n} sources, origin not isolated]",
                                urls[0], 20)
                            findings.append({"type": claim, "value": v, "url": urls[0],
                                             "sources": []})

            for url, text in texts:
                for sp in extract_spouse_names(text):
                    if sp not in spouses:
                        spouses.append(sp)
                        add("reported spouse", sp, url, _NAME_ONLY_CONF)

            if ctx.request.web and search_available():
                queries = [f'"{name}"', f'"{name}" wife OR husband OR spouse']
                district = getattr(ctx.person, "district", None) if ctx.person is not None else None
                if district:
                    queries = [f'"{name}" {district}', queries[1]]
                found = await search_candidates_free(queries)
                for url in found:
                    add("possible web mention", found[url] or url, url, _SEARCH_CONF)
                    findings.append({"type": "search", "url": url})
            return AgentResult(agent=self.name, ok=True, facts=facts, data=data)
        except Exception as e:
            return AgentResult(agent=self.name, ok=False, facts=facts, data=data, error=str(e))
