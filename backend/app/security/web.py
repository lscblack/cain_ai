"""Read-only web capability for KAI (search / open a page / geocode a place).

These are benign network reads, so ``service.run_operation`` does not gate them
behind ``tools_enabled`` — only rate-limits, records and audits them. The actual
work is delegated to existing subsystems:

- search   → app.security.adapters.web_search (keyless engine pool)
- open_url → app.security.adapters.web_fetch  (SSRF-guarded single-page fetch)
- geocode  → OpenStreetMap Nominatim (keyless), returning lat/lon the chat map
             card can render.
"""
from __future__ import annotations

import re

WEB_SEARCH_OP_KEY = "web.search"
WEB_OPEN_OP_KEY = "web.open"
MAPS_FIND_OP_KEY = "maps.find"

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "KAI-OSINT/0.1 (local intelligence workspace)"

# "near me" style phrases can't be geocoded server-side (no user location) — the
# UI resolves those against the browser's location. We detect them so the result
# carries a hint, and strip amenity/category words so "hospitals in Kigali"
# geocodes the PLACE ("Kigali") for the map to then search around.
_NEAR_ME_RE = re.compile(r"\b(near|around|close to|next to|by)\s+(me|here|my\s+location|us)\b", re.I)
_AMENITY_WORDS = {
    "hospital", "hospitals", "clinic", "clinics", "police", "pharmacy", "pharmacies",
    "chemist", "fuel", "gas", "petrol", "station", "stations", "atm", "atms", "bank",
    "banks", "restaurant", "restaurants", "food", "school", "schools", "hotel",
    "hotels", "supermarket", "supermarkets", "market", "grocery", "cafe", "cafes",
}
_CONNECTORS = (" in ", " near ", " around ", " close to ", " within ", " at ")


def _clean_place(query: str) -> tuple[str, bool]:
    """Return (place_to_geocode, near_me). Empty place => nothing geocodable
    server-side (a pure 'near me' / bare-category query)."""
    q = (query or "").strip()
    near_me = bool(_NEAR_ME_RE.search(q))
    q = _NEAR_ME_RE.sub("", q).strip(" ,")
    low = q.lower()
    # If there's a connector, keep the part after the LAST one (the place).
    for sep in _CONNECTORS:
        if sep in low:
            idx = low.rfind(sep)
            q = q[idx + len(sep):].strip(" ,")
            low = q.lower()
    # Strip leading category words ("hospitals kigali" -> "kigali").
    tokens = [t for t in re.split(r"\s+", q) if t]
    while tokens and tokens[0].lower().strip(",") in _AMENITY_WORDS:
        tokens.pop(0)
    cleaned = " ".join(tokens).strip(" ,")
    if cleaned.lower() in ("", "me", "here", "my location", "us"):
        return "", near_me
    return cleaned, near_me


async def search(query: str, *, max_results: int = 8) -> dict:
    """Open-web search. Returns ``{ok, query, results:[{title,url,snippet}]}``."""
    from app.security import adapters

    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "query is required", "results": []}
    try:
        raw = await adapters.web_search({"query": query})
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "query": query, "error": str(exc), "results": []}

    results = []
    for r in (raw.get("results") or [])[: max(1, int(max_results or 8))]:
        results.append({
            "title": r.get("title") or r.get("domain") or r.get("url") or "",
            "url": r.get("url") or "",
            "snippet": r.get("snippet") or r.get("domain") or "",
        })
    return {
        "ok": True,
        "query": query,
        "count": len(results),
        "results": results,
        "note": raw.get("note", ""),
    }


async def open_url(url: str) -> dict:
    """Fetch and read ONE public page's text. Returns ``{ok, url, title, text}``."""
    from app.security import adapters

    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "url is required"}
    try:
        data = await adapters.web_fetch({"url": url})
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "url": url, "error": str(exc)}
    return data


async def geocode(query: str, *, limit: int = 10) -> dict:
    """Geocode a place / POI via Nominatim. Returns ``{ok, query, results}`` with
    each result carrying ``lat``/``lon`` so the chat map card can plot it."""
    import httpx

    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "query is required", "results": []}

    place, near_me = _clean_place(query)
    # Pure "near me" / bare-category query: nothing to geocode server-side; the
    # UI will center on the browser's location and search the amenity there.
    if not place:
        return {"ok": True, "query": query, "count": 0, "results": [],
                "near_me": near_me,
                "note": ("This is a 'near me' / category query — resolved against your "
                         "browser location in the map card, not the server.")}

    params = {
        "q": place,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": max(1, min(int(limit or 10), 25)),
    }
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _USER_AGENT}) as client:
            resp = await client.get(_NOMINATIM_URL, params=params)
        if resp.status_code != 200:
            return {"ok": False, "query": query, "error": f"geocoder HTTP {resp.status_code}", "results": []}
        rows = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "query": query, "error": str(exc), "results": []}

    results = []
    for r in rows if isinstance(rows, list) else []:
        try:
            lat = float(r.get("lat"))
            lon = float(r.get("lon"))
        except (TypeError, ValueError):
            continue
        results.append({
            "name": r.get("display_name") or place,
            "lat": lat,
            "lon": lon,
            "category": r.get("category") or r.get("type"),
            "type": r.get("type"),
            "address": r.get("address") or {},
        })
    return {"ok": True, "query": query, "place": place, "near_me": near_me,
            "count": len(results), "results": results}
