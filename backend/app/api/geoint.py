"""GEOINT map capability: keyless layer catalogue (elevation/evidence routes append below)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

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
