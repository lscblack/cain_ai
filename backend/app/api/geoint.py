"""GEOINT map capability: keyless layer catalogue (elevation/evidence routes append below)."""
from __future__ import annotations

import math
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.api.investigations import _get_investigation_or_404
from app.database.models.evidence import Evidence
from app.database.models.user import User
from app.database.repositories.graph_repos import EntityRepository, EvidenceRepository
from app.database.session import get_session
from app.schemas.investigation import EvidenceOut

class _SafeValidationRoute(APIRoute):
    """422s without echoing the offending input.

    FastAPI's default 422 body includes each error's ``input``. A client can send a literal
    ``NaN``/``Infinity`` (Python's json parser accepts them); the response encoder then refuses
    to serialise that echoed value and the request ends in a 500 instead of a 422. Returning
    only loc/msg/type keeps validation failures a clean 4xx on this router.
    """

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                detail = [
                    {"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "invalid")), "type": str(e.get("type", "value_error"))}
                    for e in exc.errors()
                ]
                return JSONResponse(status_code=422, content={"detail": detail})

        return safe_handler


router = APIRouter(prefix="/geoint", tags=["geoint"], route_class=_SafeValidationRoute)

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
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
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


_GEOM_TYPES = {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}


def _num(x: object) -> bool:
    """A finite real number (bool is an int subclass in Python — reject it explicitly)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _position(p: object) -> bool:
    """[lng, lat(, alt)] of finite numbers with a sane latitude. Longitude is deliberately
    NOT range-checked: Leaflet does not wrap it when panning past the antimeridian, so a
    legitimate annotation can carry lng outside ±180."""
    return isinstance(p, list) and len(p) >= 2 and all(_num(v) for v in p) and abs(p[1]) <= 90


def _line(c: object, minimum: int = 2) -> bool:
    return isinstance(c, list) and len(c) >= minimum and all(_position(p) for p in c)


def _ring(c: object) -> bool:
    return _line(c, 4) and c[0] == c[-1]


def _coords_valid(t: str, c: object) -> bool:
    if t == "Point":
        return _position(c)
    if t == "MultiPoint":
        return isinstance(c, list) and all(_position(p) for p in c)
    if t == "LineString":
        return _line(c)
    if t == "MultiLineString":
        return isinstance(c, list) and all(_line(x) for x in c)
    if t == "Polygon":
        return isinstance(c, list) and len(c) >= 1 and all(_ring(r) for r in c)
    if t == "MultiPolygon":
        return isinstance(c, list) and all(
            isinstance(poly, list) and len(poly) >= 1 and all(_ring(r) for r in poly) for poly in c
        )
    return False


def _valid_geometry(g: object) -> bool:
    """null geometry is allowed by GeoJSON; otherwise a known type with well-formed coordinates."""
    if g is None:
        return True
    if not isinstance(g, dict):
        return False
    t = g.get("type")
    if t == "GeometryCollection":
        geoms = g.get("geometries")
        return isinstance(geoms, list) and all(isinstance(x, dict) and _valid_geometry(x) for x in geoms)
    return t in _GEOM_TYPES and _coords_valid(t, g.get("coordinates"))


class GeointEvidenceCreate(BaseModel):
    investigation_id: uuid.UUID
    annotations: dict
    layer_id: str
    dates: list[str] = Field(default_factory=list, max_length=2)
    bounds: dict
    note: str | None = None
    provider_url: str
    collected_at: datetime | None = None
    entity_id: uuid.UUID | None = None

    @field_validator("annotations")
    @classmethod
    def _feature_collection(cls, v: dict) -> dict:
        if v.get("type") != "FeatureCollection" or not isinstance(v.get("features"), list):
            raise ValueError("annotations must be a GeoJSON FeatureCollection")
        for f in v["features"]:
            if not isinstance(f, dict) or not _valid_geometry(f.get("geometry")):
                raise ValueError("annotations contain a feature with invalid geometry")
        return v

    @field_validator("provider_url")
    @classmethod
    def _https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("provider_url must be https")
        return v


def _parse_date(s: str) -> datetime:
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_date")
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@router.post("/evidence", response_model=EvidenceOut, status_code=status.HTTP_201_CREATED)
async def save_geoint_evidence(
    body: GeointEvidenceCreate,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> EvidenceOut:
    # Validation (422) happens in the model; 404 check precedes any write.
    await _get_investigation_or_404(body.investigation_id, session)
    if body.entity_id is not None:
        if not await EntityRepository(session).exists_in_investigation(body.entity_id, body.investigation_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="entity_not_in_investigation")
    collected = (
        _parse_date(body.dates[-1]) if body.dates
        else body.collected_at or datetime.now(timezone.utc)
    )
    ev = await EvidenceRepository(session).add(
        Evidence(
            investigation_id=body.investigation_id,
            entity_id=body.entity_id,
            type="geoint",
            source_url=body.provider_url,
            collected_at=collected,
            raw_metadata={
                "annotations": body.annotations,
                "layer_id": body.layer_id,
                "dates": body.dates,
                "bounds": body.bounds,
                "note": body.note,
            },
            processed_metadata={},
        )
    )
    await session.flush()
    return EvidenceOut(**ev.model_dump())
