"""GEOINT map capability: keyless layer catalogue (elevation/evidence routes append below)."""
from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_operator
from app.database.models.user import User

router = APIRouter(prefix="/geoint", tags=["geoint"])

_OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services"
_GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"

# Static, keyless catalogue. Never put a secret in here.
LAYERS: list[dict] = [
    {"id": "osm_dark", "kind": "base", "label": "OpenStreetMap (dark)",
     "url_template": _OSM, "attribution": "© OpenStreetMap contributors",
     "dated": False, "max_zoom": 19},
    {"id": "osm", "kind": "base", "label": "OpenStreetMap",
     "url_template": _OSM, "attribution": "© OpenStreetMap contributors",
     "dated": False, "max_zoom": 19},
    {"id": "esri_imagery", "kind": "base", "label": "Esri World Imagery",
     "url_template": f"{_ESRI}/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",
     "attribution": "Imagery © Esri, Maxar, Earthstar Geographics",
     "dated": False, "max_zoom": 19},
    {"id": "esri_hillshade", "kind": "overlay", "label": "Esri Hillshade",
     "url_template": f"{_ESRI}/Elevation/World_Hillshade/MapServer/tile/{{z}}/{{y}}/{{x}}",
     "attribution": "© Esri", "dated": False, "max_zoom": 19},
    {"id": "gibs_modis_truecolor", "kind": "base", "label": "NASA MODIS Terra True Color",
     "url_template": f"{_GIBS}/MODIS_Terra_CorrectedReflectance_TrueColor/default/{{Time}}/GoogleMapsCompatible_Level9/{{z}}/{{y}}/{{x}}.jpg",
     "attribution": "NASA GIBS / EOSDIS", "dated": True, "max_zoom": 9},
    {"id": "gibs_viirs_truecolor", "kind": "base", "label": "NASA VIIRS SNPP True Color",
     "url_template": f"{_GIBS}/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/{{Time}}/GoogleMapsCompatible_Level9/{{z}}/{{y}}/{{x}}.jpg",
     "attribution": "NASA GIBS / EOSDIS", "dated": True, "max_zoom": 9},
]


@router.get("/layers")
async def list_layers(operator: User = Depends(get_current_operator)) -> dict:
    """Keyless imagery/basemap layer catalogue for the map."""
    return {"layers": LAYERS}


_OPENTOPO_URL = "https://api.opentopodata.org/v1/srtm30m"
_MAX_POINTS = 100
_ELEV_TTL_S = 600
# (rounded lat, rounded lon) -> (expires_at monotonic, elevation_m | None)
_ELEV_CACHE: dict[tuple[float, float], tuple[float, float | None]] = {}


def _parse_points(raw: str) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for chunk in raw.split("|"):
        parts = chunk.strip().split(",")
        try:
            if len(parts) != 2:
                raise ValueError
            lat, lon = float(parts[0]), float(parts[1])
        except ValueError:
            raise HTTPException(status_code=422, detail="points must be lat,lon pairs separated by |")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise HTTPException(status_code=422, detail="coordinate out of range")
        pts.append((lat, lon))
        if len(pts) >= _MAX_POINTS:
            break
    return pts


async def _fetch_opentopo(points: list[tuple[float, float]]) -> list[float | None]:
    """Query OpenTopoData (SRTM 30m, keyless); returns elevations in input order."""
    locations = "|".join(f"{lat},{lon}" for lat, lon in points)
    async with httpx.AsyncClient(timeout=8.0) as http:
        resp = await http.get(_OPENTOPO_URL, params={"locations": locations})
    if resp.status_code != 200:
        raise httpx.HTTPError(f"opentopodata status {resp.status_code}")
    results = resp.json()["results"]
    if len(results) != len(points):
        raise ValueError("opentopodata result count mismatch")
    return [r.get("elevation") for r in results]


@router.get("/elevation")
async def elevation(
    points: str = Query(..., description="lat,lon|lat,lon|..."),
    operator: User = Depends(get_current_operator),
) -> dict:
    """Elevation (SRTM) for up to 100 points, proxied + cached. Never 5xx on upstream failure."""
    pts = _parse_points(points)
    now = time.monotonic()
    keys = [(round(lat, 4), round(lon, 4)) for lat, lon in pts]
    missing = [
        k for k in dict.fromkeys(keys)
        if k not in _ELEV_CACHE or _ELEV_CACHE[k][0] <= now
    ]
    if missing:
        try:
            elevs = await _fetch_opentopo(missing)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            return {"ok": False, "reason": f"elevation upstream failed: {exc}"}
        for k, e in zip(missing, elevs):
            _ELEV_CACHE[k] = (now + _ELEV_TTL_S, e)
    return {
        "ok": True,
        "results": [
            {"lat": lat, "lon": lon, "elevation_m": _ELEV_CACHE[k][1]}
            for (lat, lon), k in zip(pts, keys)
        ],
    }
