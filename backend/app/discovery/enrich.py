"""Keyless structured enrichment from free public knowledge APIs.

Pulls real, structured facts about a subject directly from open APIs (no keys,
public data only) so an investigation shows data IMMEDIATELY — independent of the
crawl backlog. Sources:

- Wikipedia REST summary  (bio extract, short description, thumbnail)
- Wikidata (wbgetentities) (occupation, positions, employer, citizenship,
  birth/death, education, party — structured claims with resolved labels)

Everything is best-effort: any failure returns a partial/empty result, never
raises. Wikimedia's robot policy wants a descriptive UA (see search._WIKI_UA).
"""
from __future__ import annotations

from urllib.parse import quote, unquote

import httpx

from app.core.logging import get_logger
from app.discovery.search import _WIKI_UA, wikipedia_article

logger = get_logger("kai.discovery.enrich")

# Wikidata properties we surface, grouped by how the dossier renders them.
_P_TITLES = {  # -> meta.titles (roles / what they are)
    "P106": "occupation",
    "P39": "position held",
    "P512": "academic degree",
}
_P_ORGS = {  # -> meta.orgs (affiliations)
    "P108": "employer",
    "P69": "educated at",
    "P102": "political party",
    "P54": "member of sports team",
}
_P_LOCATIONS = {  # -> meta.locations
    "P27": "country of citizenship",
    "P19": "place of birth",
}
_P_DATES = {  # -> rendered into the extract/description tail
    "P569": "born",
    "P570": "died",
}


async def _get_json(url: str, *, timeout: float = 10.0) -> dict | list | None:
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": _WIKI_UA}
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("enrich GET failed %s: %s", url, exc)
        return None


async def wikipedia_summary(title: str, lang: str = "en") -> dict | None:
    """REST summary: bio extract, short description, thumbnail, canonical URL."""
    data = await _get_json(
        f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"
    )
    if not isinstance(data, dict) or data.get("type") == "disambiguation":
        return None
    return {
        "title": data.get("title") or title,
        "extract": (data.get("extract") or "").strip(),
        "description": (data.get("description") or "").strip(),
        "thumbnail": (data.get("thumbnail") or {}).get("source"),
        "url": (data.get("content_urls") or {}).get("desktop", {}).get("page"),
        "wikibase_item": data.get("wikibase_item"),
    }


async def _qid_for_title(title: str, lang: str = "en") -> str | None:
    data = await _get_json(
        f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=pageprops"
        f"&ppprop=wikibase_item&redirects=1&titles={quote(title)}&format=json"
    )
    try:
        pages = (data or {}).get("query", {}).get("pages", {})
        for p in pages.values():
            qid = (p.get("pageprops") or {}).get("wikibase_item")
            if qid:
                return qid
    except Exception:  # noqa: BLE001
        pass
    return None


def _claim_qids(claims: dict, prop: str) -> list[str]:
    out: list[str] = []
    for c in claims.get(prop, []) or []:
        try:
            dv = c["mainsnak"]["datavalue"]["value"]
            if isinstance(dv, dict) and "id" in dv:
                out.append(dv["id"])
        except Exception:  # noqa: BLE001
            continue
    return out


def _claim_times(claims: dict, prop: str) -> list[str]:
    out: list[str] = []
    for c in claims.get(prop, []) or []:
        try:
            t = c["mainsnak"]["datavalue"]["value"]["time"]  # e.g. +1957-10-23T00:00:00Z
            year = t.lstrip("+").split("-")[0]
            if year:
                out.append(year)
        except Exception:  # noqa: BLE001
            continue
    return out


async def wikidata_facts(qid: str) -> dict:
    """Structured claims for a Wikidata entity, with referenced labels resolved."""
    data = await _get_json(
        f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={qid}"
        f"&props=claims&format=json"
    )
    try:
        claims = data["entities"][qid]["claims"]
    except Exception:  # noqa: BLE001
        return {}

    wanted = {**_P_TITLES, **_P_ORGS, **_P_LOCATIONS}
    ref_qids: set[str] = set()
    by_prop: dict[str, list[str]] = {}
    for prop in wanted:
        ids = _claim_qids(claims, prop)
        if ids:
            by_prop[prop] = ids
            ref_qids.update(ids)

    labels: dict[str, str] = {}
    ids_list = list(ref_qids)
    for i in range(0, len(ids_list), 50):  # wbgetentities caps at 50 ids/call
        chunk = ids_list[i : i + 50]
        ld = await _get_json(
            "https://www.wikidata.org/w/api.php?action=wbgetentities"
            f"&ids={'|'.join(chunk)}&props=labels&languages=en&format=json"
        )
        try:
            for q, ent in ld["entities"].items():
                lab = (ent.get("labels") or {}).get("en", {}).get("value")
                if lab:
                    labels[q] = lab
        except Exception:  # noqa: BLE001
            continue

    def resolve(prop: str) -> list[str]:
        return [labels[q] for q in by_prop.get(prop, []) if q in labels]

    out: dict[str, list[str]] = {
        "titles": [], "orgs": [], "locations": [], "born": [], "died": [],
    }
    for prop in _P_TITLES:
        out["titles"] += resolve(prop)
    for prop in _P_ORGS:
        out["orgs"] += resolve(prop)
    for prop in _P_LOCATIONS:
        out["locations"] += resolve(prop)
    out["born"] = _claim_times(claims, "P569")
    out["died"] = _claim_times(claims, "P570")
    # de-dup, keep order
    for k in ("titles", "orgs", "locations"):
        out[k] = list(dict.fromkeys(out[k]))
    return out


async def enrich_subject(name: str) -> dict | None:
    """Full keyless profile for a named subject → ready to store on a Page.

    Returns {title, url, extract, description, thumbnail, titles[], orgs[],
    locations[], born[], died[]} or None if the subject isn't found.
    """
    art = await wikipedia_article(name)
    if art is None:
        return None
    url, art_title = art
    # article title from the URL path segment (what the APIs key on)
    page_title = unquote(url.rstrip("/").rsplit("/", 1)[-1]) or art_title

    summary = await wikipedia_summary(page_title) or {}
    qid = summary.get("wikibase_item") or await _qid_for_title(page_title)
    facts = await wikidata_facts(qid) if qid else {}

    extract = summary.get("extract") or ""
    bits = []
    if facts.get("born"):
        bits.append(f"born {facts['born'][0]}")
    if facts.get("died"):
        bits.append(f"died {facts['died'][0]}")
    tail = f" ({'; '.join(bits)})" if bits else ""

    return {
        "title": summary.get("title") or art_title,
        "url": summary.get("url") or url,
        "extract": extract,
        "description": (summary.get("description") or "") + tail,
        "thumbnail": summary.get("thumbnail"),
        "titles": facts.get("titles", []),
        "orgs": facts.get("orgs", []),
        "locations": facts.get("locations", []),
        "born": facts.get("born", []),
        "died": facts.get("died", []),
        "qid": qid,
    }
