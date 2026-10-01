"""Live geo-intelligence providers.

Each provider is key-gated: if its credential is absent it reports UNAVAILABLE
rather than returning fabricated points. External transports are injectable so
the logic is unit-testable offline; the default transports make the real calls.

Point shape: {lat, lon, label, kind, meta}.
"""
from __future__ import annotations

import csv
import io
import time
from typing import Any, Awaitable, Callable

from app.core.config import get_settings

JsonGet = Callable[..., Awaitable[dict]]
TextGet = Callable[..., Awaitable[str]]


# ─────────────────────────── OpenSky (aircraft) ───────────────────────────
_OPENSKY_TOKEN: dict[str, Any] = {"token": None, "exp": 0.0}


async def _opensky_token() -> str | None:
    s = get_settings()
    if not (s.opensky_client_id and s.opensky_client_secret):
        return None
    if _OPENSKY_TOKEN["token"] and _OPENSKY_TOKEN["exp"] > time.time() + 30:
        return _OPENSKY_TOKEN["token"]
    import httpx

    url = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": s.opensky_client_id,
                "client_secret": s.opensky_client_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    _OPENSKY_TOKEN["token"] = data["access_token"]
    _OPENSKY_TOKEN["exp"] = time.time() + int(data.get("expires_in", 1800))
    return _OPENSKY_TOKEN["token"]


def aircraft_configured() -> bool:
    s = get_settings()
    return bool(s.opensky_client_id and s.opensky_client_secret)


async def fetch_aircraft(bbox: tuple[float, float, float, float] | None = None, *, _states=None) -> list[dict]:
    """bbox = (lamin, lomin, lamax, lomax). _states injectable for tests."""
    if _states is None:
        token = await _opensky_token()
        if token is None:
            return []
        import httpx

        params = {}
        if bbox:
            params = {"lamin": bbox[0], "lomin": bbox[1], "lamax": bbox[2], "lomax": bbox[3]}
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(
                "https://opensky-network.org/api/states/all",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            _states = resp.json().get("states") or []
    out = []
    for st in _states:
        try:
            lon, lat = st[5], st[6]
            if lon is None or lat is None:
                continue
            out.append(
                {
                    "lat": float(lat),
                    "lon": float(lon),
                    "label": (st[1] or st[0] or "aircraft").strip(),
                    "kind": "aircraft",
                    "meta": {"icao24": st[0], "origin_country": st[2], "velocity": st[9], "alt": st[7]},
                }
            )
        except (IndexError, TypeError, ValueError):
            continue
    return out


# ─────────────────────────── Windy webcams (CCTV) ───────────────────────────
def webcams_configured() -> bool:
    return bool(get_settings().windy_webcams_api_key)


async def fetch_webcams(countries: list[str] | None = None, *, _json_get: JsonGet | None = None) -> list[dict]:
    s = get_settings()
    if not s.windy_webcams_api_key:
        return []
    countries = countries or [c for c in s.windy_webcams_countries.split(",") if c.strip()]
    params = {"limit": 50, "include": "location,urls,images"}
    if countries:
        params["countries"] = ",".join(countries)

    async def _default(url, params, headers):
        import httpx

        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            return r.json()

    getter = _json_get or _default
    data = await getter(
        "https://api.windy.com/webcams/api/v3/webcams",
        params,
        {"x-windy-api-key": s.windy_webcams_api_key},
    )
    out = []
    for w in data.get("webcams", []) or []:
        loc = w.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if lat is None or lon is None:
            continue
        urls = w.get("urls") or {}
        out.append(
            {
                "lat": float(lat),
                "lon": float(lon),
                "label": w.get("title") or "webcam",
                "kind": "cctv",
                "meta": {
                    "city": loc.get("city"),
                    "country": loc.get("country"),
                    "detail_url": (urls.get("detail") if isinstance(urls, dict) else None),
                },
            }
        )
    return out


# ─────────────────────────── NASA FIRMS (satellite fires) ───────────────────
def fires_configured() -> bool:
    return bool(get_settings().firms_map_key)


async def fetch_fires(area: str = "world", day_range: int = 1, *, _csv_text: str | None = None) -> list[dict]:
    s = get_settings()
    if not s.firms_map_key:
        return []
    if _csv_text is None:
        import httpx

        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{s.firms_map_key}/VIIRS_SNPP_NRT/{area}/{day_range}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            _csv_text = r.text
    out = []
    reader = csv.DictReader(io.StringIO(_csv_text))
    for row in reader:
        try:
            out.append(
                {
                    "lat": float(row["latitude"]),
                    "lon": float(row["longitude"]),
                    "label": f"fire {row.get('acq_date','')} {row.get('acq_time','')}",
                    "kind": "satellite_fire",
                    "meta": {"confidence": row.get("confidence"), "frp": row.get("frp")},
                }
            )
        except (KeyError, ValueError, TypeError):
            continue
        if len(out) >= 2000:
            break
    return out


# ─────────────────────────── AISStream (vessels) ───────────────────────────
def vessels_configured() -> bool:
    return bool(get_settings().aisstream_api_key)


async def fetch_vessels(
    bbox: tuple[float, float, float, float],
    *,
    seconds: float = 6.0,
    max_points: int = 200,
    _messages: list[dict] | None = None,
) -> list[dict]:
    """bbox = (lat_min, lon_min, lat_max, lon_max). Collects live position reports
    for `seconds`. `_messages` injectable for tests."""
    s = get_settings()
    if not s.aisstream_api_key:
        return []
    seen: dict[str, dict] = {}

    def _ingest(msg: dict) -> None:
        meta = msg.get("MetaData") or {}
        lat, lon = meta.get("latitude"), meta.get("longitude")
        if lat is None or lon is None:
            return
        mmsi = str(meta.get("MMSI") or meta.get("MMSI_String") or f"{lat},{lon}")
        seen[mmsi] = {
            "lat": float(lat),
            "lon": float(lon),
            "label": (meta.get("ShipName") or f"MMSI {mmsi}").strip(),
            "kind": "vessel",
            "meta": {"mmsi": mmsi},
        }

    if _messages is not None:
        for m in _messages:
            _ingest(m)
        return list(seen.values())[:max_points]

    import json as _json

    import websockets

    sub = {
        "APIKey": s.aisstream_api_key,
        "BoundingBoxes": [[[bbox[0], bbox[1]], [bbox[2], bbox[3]]]],
        "FilterMessageTypes": ["PositionReport"],
    }
    deadline = time.time() + seconds
    try:
        async with websockets.connect("wss://stream.aisstream.io/v0/stream", open_timeout=10) as ws:
            await ws.send(_json.dumps(sub))
            while time.time() < deadline and len(seen) < max_points:
                try:
                    raw = await ws.recv()
                except Exception:
                    break
                try:
                    _ingest(_json.loads(raw))
                except Exception:
                    continue
    except Exception:
        return list(seen.values())[:max_points]
    return list(seen.values())[:max_points]
