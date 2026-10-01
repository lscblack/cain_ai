"""Live geo-intelligence layers for the map (aircraft, vessels, fires, webcams)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_operator
from app.core.config import get_settings
from app.database.models.user import User
from app.providers import geo

router = APIRouter(prefix="/geo", tags=["geo"])


@router.get("/config")
async def geo_config(operator: User = Depends(get_current_operator)) -> dict:
    """Client-usable map tile tokens (TomTom/Cesium are browser tokens by design)
    plus which live layers are configured. No server-only secret is returned."""
    s = get_settings()
    return {
        "tomtom_key": s.tomtom_api_key or None,
        "cesium_token": s.cesium_ion_token or None,
        "layers": {
            "aircraft": geo.aircraft_configured(),
            "vessels": geo.vessels_configured(),
            "satellite_fires": geo.fires_configured(),
            "cctv": geo.webcams_configured(),
        },
    }


def _bbox(lat_min, lon_min, lat_max, lon_max):
    if None in (lat_min, lon_min, lat_max, lon_max):
        return None
    return (lat_min, lon_min, lat_max, lon_max)


@router.get("/aircraft")
async def aircraft(
    lat_min: float | None = Query(None), lon_min: float | None = Query(None),
    lat_max: float | None = Query(None), lon_max: float | None = Query(None),
    operator: User = Depends(get_current_operator),
) -> dict:
    if not geo.aircraft_configured():
        return {"available": False, "detail": "opensky_not_configured", "points": []}
    points = await geo.fetch_aircraft(_bbox(lat_min, lon_min, lat_max, lon_max))
    return {"available": True, "points": points, "count": len(points)}


@router.get("/vessels")
async def vessels(
    lat_min: float = Query(...), lon_min: float = Query(...),
    lat_max: float = Query(...), lon_max: float = Query(...),
    seconds: float = Query(6.0, ge=1.0, le=15.0),
    operator: User = Depends(get_current_operator),
) -> dict:
    if not geo.vessels_configured():
        return {"available": False, "detail": "aisstream_not_configured", "points": []}
    points = await geo.fetch_vessels((lat_min, lon_min, lat_max, lon_max), seconds=seconds)
    return {"available": True, "points": points, "count": len(points)}


@router.get("/fires")
async def fires(
    area: str = Query("world", max_length=64),
    day_range: int = Query(1, ge=1, le=10),
    operator: User = Depends(get_current_operator),
) -> dict:
    if not geo.fires_configured():
        return {"available": False, "detail": "firms_not_configured", "points": []}
    points = await geo.fetch_fires(area=area, day_range=day_range)
    return {"available": True, "points": points, "count": len(points)}


@router.get("/webcams")
async def webcams(
    country: str | None = Query(None, max_length=64),
    operator: User = Depends(get_current_operator),
) -> dict:
    if not geo.webcams_configured():
        return {"available": False, "detail": "windy_not_configured", "points": []}
    countries = [c.strip() for c in country.split(",")] if country else None
    points = await geo.fetch_webcams(countries)
    return {"available": True, "points": points, "count": len(points)}
