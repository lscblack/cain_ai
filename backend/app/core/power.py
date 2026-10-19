"""Browser-controlled stop/start of KAI's background engine.

STOP halts the crawl/discovery worker (the service that continuously uses the
CPU) and unloads the local model from RAM. START brings the worker back; the
model reloads on the next chat. The API/UI backend itself stays up the whole
time so it can be toggled again from the browser.

systemctl --user is reached over the user D-Bus, so the control commands are run
with the session env vars (XDG_RUNTIME_DIR / DBUS_SESSION_BUS_ADDRESS) that the
backend service inherits — the tool executor's base env strips those.
"""
from __future__ import annotations

import os
import shutil

from app.core.config import get_settings
from app.security.executor import run_argv

POWER_KEY = "kai:power:stopped"
WORKER_UNIT = "kai-worker.service"


def _session_env() -> dict:
    env: dict = {}
    for k in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        v = os.environ.get(k)
        if v:
            env[k] = v
    return env


async def _systemctl(action: str, unit: str) -> dict:
    sc = shutil.which("systemctl")
    if not sc:
        return {"ok": False, "error": "systemctl not found"}
    res = await run_argv([sc, "--user", action, unit], timeout=30, env_extra=_session_env())
    return {
        "ok": res.status == "ok",
        "status": res.status,
        "error": res.error,
        "detail": (res.stderr or res.stdout or "").strip()[:500] or None,
    }


async def _worker_active() -> bool:
    sc = shutil.which("systemctl")
    if not sc:
        return False
    res = await run_argv([sc, "--user", "is-active", WORKER_UNIT], timeout=10, env_extra=_session_env())
    return res.stdout.strip() == "active"


async def _model_loaded() -> bool:
    try:
        import httpx

        s = get_settings()
        async with httpx.AsyncClient(base_url=s.ollama_base_url, timeout=3.0) as c:
            r = await c.get("/api/ps")
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
        return any(s.kai_ollama_model in n for n in names)
    except Exception:  # noqa: BLE001
        return False


async def _ollama_unload() -> None:
    ol = shutil.which("ollama")
    if ol:
        await run_argv([ol, "stop", get_settings().kai_ollama_model], timeout=30)


async def stop_kai(redis) -> dict:
    worker = await _systemctl("stop", WORKER_UNIT)
    await _ollama_unload()
    try:
        await redis.set(POWER_KEY, "1")
    except Exception:  # noqa: BLE001
        pass
    return {"running": False, "worker": worker}


async def start_kai(redis) -> dict:
    worker = await _systemctl("start", WORKER_UNIT)
    try:
        await redis.delete(POWER_KEY)
    except Exception:  # noqa: BLE001
        pass
    return {"running": worker.get("ok", False), "worker": worker}


async def is_stopped(redis) -> bool:
    try:
        return bool(await redis.get(POWER_KEY))
    except Exception:  # noqa: BLE001
        return False


async def power_status(redis) -> dict:
    worker = await _worker_active()
    stopped_flag = await is_stopped(redis)
    return {
        "running": worker,
        "worker_active": worker,
        "stopped_flag": stopped_flag,
        "model_loaded": await _model_loaded(),
        "worker_unit": WORKER_UNIT,
    }
