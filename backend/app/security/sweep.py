"""OSINT sweep — interconnect installed tools with a subject's identifiers.

Given identifiers surfaced elsewhere in KAI (a person search's emails/usernames/
phones, a domain, a host), run every applicable INSTALLED passive tool and
return the combined results. Each run goes through the hardened service (argv,
validation, caps, audit), so a sweep is just a convenient fan-out over the same
safe executor the chat model uses.

Only passive operations are swept automatically (no active scanning fan-out).
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.security import registry, service

# identifier kind → ordered list of operation keys to try (passive only)
_PLAN: dict[str, list[str]] = {
    "domain": [
        "dns.records", "whois.lookup", "host.lookup", "theharvester.search",
        "sublist3r.enum", "amass.passive", "subfinder.enum", "assetfinder.find",
        "gau.urls", "waybackurls.urls", "dnstracer.trace",
    ],
    "host": [
        "http.headers", "tls.inspect", "whatweb.scan", "wafw00f.detect",
        "httpx.probe", "sslscan.scan", "sslyze.scan", "mtr.report",
    ],
    "url": ["http.headers", "whatweb.scan", "wafw00f.detect", "httpx.probe"],
    "email": ["holehe.check"],
    "username": ["sherlock.hunt", "maigret.scan", "socialscan.check"],
    "phone": ["phoneinfoga.scan"],
    "ip": ["geoip.lookup", "whois.lookup"],
}

# which param each op expects (its single target param name)
def _target(op_key: str) -> tuple[str | None, str | None]:
    """Return (param_name, kind) for the op's single target param."""
    found = registry.get_operation(op_key)
    if not found:
        return None, None
    _tool, op = found
    if op.params:
        return op.params[0].name, op.params[0].kind
    return op.target_param, None


async def _installed_op_keys() -> set[str]:
    tools = list(registry.ALL_TOOLS)
    discs = await asyncio.gather(*(registry.discover(t) for t in tools))
    installed = {t.name for t, d in zip(tools, discs) if d.installed}
    return {op.key for t, op in registry.all_operations() if t.name in installed}


def _summary(result: dict) -> str:
    if result.get("result"):
        import json
        return json.dumps(result["result"])[:600]
    out = (result.get("stdout") or "").strip()
    err = (result.get("stderr") or "").strip()
    text = out or err or result.get("message") or result.get("error") or ""
    return text[:600]


async def run_osint_sweep(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    identifiers: list[tuple[str, str]],   # (kind, value)
    conversation_id: uuid.UUID | None = None,
    max_ops: int = 25,
) -> dict:
    installed = await _installed_op_keys()
    results: list[dict] = []
    planned: list[tuple[str, str, str]] = []  # (kind, value, op_key)
    for kind, value in identifiers:
        for op_key in _PLAN.get(kind, []):
            if op_key in installed:
                planned.append((kind, value, op_key))

    skipped = max(0, len(planned) - max_ops)
    for kind, value, op_key in planned[:max_ops]:
        pname, pkind = _target(op_key)
        if not pname:
            continue
        val = value
        # a url-kind op fed a bare host/domain needs a scheme
        if pkind == "url" and "://" not in val:
            val = "https://" + val.rstrip("/") + "/"
        res = await service.run_operation(
            session, user_id=user_id, op_key=op_key,
            params={pname: val}, conversation_id=conversation_id,
        )
        results.append({
            "identifier": value, "kind": kind, "operation": op_key,
            "tool": res.get("tool"), "status": res.get("status"),
            "ok": bool(res.get("ok")), "execution_id": res.get("execution_id"),
            "summary": _summary(res),
        })

    return {
        "identifiers": [{"kind": k, "value": v} for k, v in identifiers],
        "ran": len(results),
        "skipped": skipped,
        "results": results,
        "note": (
            "Ran installed passive OSINT tools over the given identifiers. "
            "Missing tools can be installed via the approval workflow."
        ),
    }
