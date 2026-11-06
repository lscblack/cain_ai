"""HTTP client for calling a registered :class:`ExternalEndpoint`.

Handles template + secret resolution, authentication (none / bearer-token with
caching / static header key / basic), the request itself, and extraction of the
useful payload and any base64 image fields.

These endpoints are the operator's OWN internal databases (localhost / private
hosts), so the public-URL SSRF guard used elsewhere does NOT apply here — it
would wrongly block 127.0.0.1. Credentials are read from the environment by name
at call time and are never logged.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.database.models.enrich import ExternalEndpoint

_ENV_RE = re.compile(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}")
_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# endpoint.id -> (token, expires_at_monotonic)
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}

# Live view of the project .env so an operator can change endpoint bases/secrets
# (e.g. IDENTITY_API_BASE) and have the NEXT call pick them up WITHOUT restarting
# the backend. ``load_dotenv`` only runs at startup, so os.environ would otherwise
# hold the stale value. We re-parse .env when its mtime changes and prefer its
# value over os.environ for {env:VAR}.
_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
_ENV_FILE_CACHE: dict[str, Any] = {"mtime": None, "values": {}}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key:
            values[key] = val
    return values


def _env_value(name: str) -> str:
    """Resolve an env var, preferring a live read of .env (so edits take effect
    without a restart), then falling back to the process environment."""
    try:
        mtime = _ROOT_ENV.stat().st_mtime
    except OSError:
        mtime = None
    if mtime != _ENV_FILE_CACHE["mtime"]:
        _ENV_FILE_CACHE["values"] = _parse_env_file(_ROOT_ENV)
        _ENV_FILE_CACHE["mtime"] = mtime
    file_vals = _ENV_FILE_CACHE["values"]
    if name in file_vals and file_vals[name] != "":
        return file_vals[name]
    return os.environ.get(name, "")


@dataclass
class EndpointResult:
    ok: bool
    status: int = 0
    url: str = ""
    data: Any = None          # payload at result_path
    raw: Any = None           # full parsed JSON
    images: dict[str, str] = field(default_factory=dict)  # image_key -> base64
    error: str | None = None


def _resolve_str(template: str, params: dict) -> str:
    """Resolve ``{env:VAR}`` and ``{param}`` placeholders in a string."""
    if not isinstance(template, str):
        return template
    out = _ENV_RE.sub(lambda m: _env_value(m.group(1)), template)

    def _param(m: re.Match) -> str:
        key = m.group(1)
        val = params.get(key)
        return "" if val is None else str(val)

    return _PARAM_RE.sub(_param, out)


def _resolve(obj: Any, params: dict) -> Any:
    if isinstance(obj, str):
        return _resolve_str(obj, params)
    if isinstance(obj, dict):
        return {k: _resolve(v, params) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(v, params) for v in obj]
    return obj


def dotted_get(obj: Any, path: str) -> Any:
    """Follow a dotted path into nested dicts. Empty path returns obj."""
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


async def _mint_bearer_token(endpoint: ExternalEndpoint, params: dict) -> str | None:
    cfg = endpoint.auth_config or {}
    cache_ttl = int(cfg.get("cache_ttl_s", 300))
    cached = _TOKEN_CACHE.get(str(endpoint.id))
    if cached and cached[1] > time.monotonic():
        return cached[0]

    token_url = _resolve_str(str(cfg.get("token_url", "")), params)
    if not token_url:
        return None
    method = str(cfg.get("token_method", "POST")).upper()
    body = _resolve(cfg.get("token_body", {}), params)
    token_field = str(cfg.get("token_field", "token"))
    headers = _resolve(cfg.get("token_headers", {"Content-Type": "application/json"}), params)

    async with httpx.AsyncClient(timeout=20) as client:
        if method == "GET":
            resp = await client.get(token_url, params=body or None, headers=headers)
        else:
            resp = await client.post(token_url, json=body or None, headers=headers)
    if resp.status_code >= 400:
        raise RuntimeError(f"token endpoint HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError:
        payload = {"token": resp.text.strip()}
    token = dotted_get(payload, token_field)
    if not token:
        raise RuntimeError(f"token field '{token_field}' not in auth response")
    token = str(token)
    _TOKEN_CACHE[str(endpoint.id)] = (token, time.monotonic() + cache_ttl)
    return token


def invalidate_token(endpoint_id: str) -> None:
    _TOKEN_CACHE.pop(str(endpoint_id), None)


async def _apply_auth(
    endpoint: ExternalEndpoint, params: dict, headers: dict, auth: dict
) -> httpx.Auth | None:
    """Mutate ``headers`` and return an httpx auth object if basic auth is used."""
    cfg = endpoint.auth_config or {}
    at = (endpoint.auth_type or "none").lower()
    if at == "bearer":
        token = await _mint_bearer_token(endpoint, params)
        if token:
            header = str(cfg.get("header", "Authorization"))
            scheme = str(cfg.get("scheme", "Bearer"))
            headers[header] = f"{scheme} {token}".strip()
    elif at == "header_key":
        name = str(cfg.get("header_name", "X-API-Key"))
        value = _resolve_str(str(cfg.get("value", "")), params)
        if value:
            headers[name] = value
    elif at == "basic":
        user = _resolve_str(str(cfg.get("username", cfg.get("username_env", ""))), params)
        pwd = _resolve_str(str(cfg.get("password", cfg.get("password_env", ""))), params)
        if user or pwd:
            return httpx.BasicAuth(user, pwd)
    return None


def _extract_images(payload: Any, image_keys: list) -> dict[str, str]:
    images: dict[str, str] = {}
    for key in image_keys or []:
        val = dotted_get(payload, str(key))
        if isinstance(val, str) and val.strip():
            images[str(key)] = val.strip()
    return images


async def call_endpoint(
    endpoint: ExternalEndpoint, params: dict | None = None, *, timeout: float = 25.0
) -> EndpointResult:
    """Call ``endpoint`` with the given params (e.g. ``{"nid": "..."}``)."""
    params = params or {}
    url = _resolve_str(endpoint.url_template, params)
    query = {k: v for k, v in (_resolve(endpoint.query_template, params) or {}).items() if v != ""}
    headers = dict(_resolve(endpoint.headers, params) or {})
    retried = False

    while True:
        try:
            auth = await _apply_auth(endpoint, params, headers, {})
        except (RuntimeError, httpx.HTTPError) as exc:
            # Token mint failed (bad/empty credentials, auth server down). Report it
            # as a normal failed result instead of raising, so one optional endpoint
            # (e.g. land parcels) can't abort the whole per-person enrichment.
            return EndpointResult(ok=False, url=url, error=f"auth failed: {exc}")
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if (endpoint.method or "GET").upper() == "POST":
                    body = _resolve(endpoint.body_template, params)
                    resp = await client.post(url, params=query or None, headers=headers,
                                             json=body or None, auth=auth)
                else:
                    resp = await client.get(url, params=query or None, headers=headers, auth=auth)
        except httpx.HTTPError as exc:
            return EndpointResult(ok=False, url=url, error=f"request failed: {exc}")

        # A stale cached bearer token → refresh once and retry.
        if resp.status_code in (401, 403) and endpoint.auth_type == "bearer" and not retried:
            invalidate_token(str(endpoint.id))
            retried = True
            continue

        if resp.status_code >= 400:
            return EndpointResult(ok=False, status=resp.status_code, url=url,
                                  error=f"HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            raw = resp.json()
        except ValueError:
            return EndpointResult(ok=False, status=resp.status_code, url=url,
                                  error="response was not JSON")
        payload = dotted_get(raw, endpoint.result_path or "")
        images = _extract_images(payload, endpoint.image_keys)
        return EndpointResult(ok=True, status=resp.status_code, url=url,
                              data=payload, raw=raw, images=images)
