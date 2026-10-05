"""Operator-managed provider keys: view (masked) and set (written to .env).

Only a fixed whitelist of keys may be set. Values are never returned — only a
masked hint and a 'configured' flag. Writing persists to .env and hot-reloads
settings so providers pick up the new keys without a restart.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_current_operator
from app.core.config import get_settings
from app.core.envfile import update_env
from app.database.models.user import User

router = APIRouter(prefix="/settings", tags=["settings"])

# setting-field (lowercase) -> (ENV name, label, secret?)
MANAGED_KEYS: dict[str, tuple[str, str, bool]] = {
    "serpapi_api_key": ("SERPAPI_API_KEY", "SerpAPI (web discovery)", True),
    "searchapi_api_key": ("SEARCHAPI_API_KEY", "SearchApi.io (web discovery, free tier)", True),
    "brave_api_key": ("BRAVE_API_KEY", "Brave Search (web discovery, free tier)", True),
    "unavatar_api_key": ("UNAVATAR_API_KEY", "unavatar (avatar resolver)", True),
    "tineye_api_key": ("TINEYE_API_KEY", "TinEye", True),
    "openrouter_api_key": ("OPENROUTER_API_KEY", "OpenRouter (AI)", True),
    "openai_api_key": ("OPENAI_API_KEY", "OpenAI (AI)", True),
    "ai_model": ("AI_MODEL", "AI model id", False),
    "tomtom_api_key": ("TOMTOM_API_KEY", "TomTom (map tiles)", True),
    "cesium_ion_token": ("CESIUM_ION_TOKEN", "Cesium Ion token", True),
    "firms_map_key": ("FIRMS_MAP_KEY", "NASA FIRMS (satellite fires)", True),
    "aisstream_api_key": ("AISSTREAM_API_KEY", "AISStream (vessels)", True),
    "opensky_client_id": ("OPENSKY_CLIENT_ID", "OpenSky client id", False),
    "opensky_client_secret": ("OPENSKY_CLIENT_SECRET", "OpenSky client secret", True),
    "windy_webcams_api_key": ("WINDY_WEBCAMS_API_KEY", "Windy Webcams", True),
    "windy_webcams_countries": ("WINDY_WEBCAMS_COUNTRIES", "Windy countries (RW,KE…)", False),
}


class KeyUpdateIn(BaseModel):
    values: dict[str, str]


def _mask(value: str, secret: bool) -> str | None:
    if not value:
        return None
    if not secret:
        return value
    return ("•" * max(0, len(value) - 4)) + value[-4:] if len(value) > 4 else "••••"


@router.get("/keys")
async def list_keys(operator: User = Depends(get_current_operator)) -> dict:
    s = get_settings()
    out = []
    for field, (env_name, label, secret) in MANAGED_KEYS.items():
        val = str(getattr(s, field, "") or "")
        out.append(
            {
                "field": field,
                "env": env_name,
                "label": label,
                "secret": secret,
                "configured": bool(val),
                "masked": _mask(val, secret),
            }
        )
    return {"keys": out}


@router.post("/keys")
async def set_keys(body: KeyUpdateIn, operator: User = Depends(get_current_operator)) -> dict:
    unknown = [k for k in body.values if k not in MANAGED_KEYS]
    if unknown:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"unknown_keys: {unknown}")

    env_values = {}
    for field, raw in body.values.items():
        env_name = MANAGED_KEYS[field][0]
        env_values[env_name] = str(raw).strip()
    update_env(env_values)

    # hot-reload: clear settings cache and dependent caches
    get_settings.cache_clear()
    import app.ai.router as ai_router
    import app.providers.geo as geo

    ai_router._provider = None
    geo._OPENSKY_TOKEN = {"token": None, "exp": 0.0}

    return {"updated": list(body.values.keys()), "count": len(body.values)}
