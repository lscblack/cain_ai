"""Operator-defined tool capabilities.

Turns a friendly capability definition into a catalogue-shaped entry that the
registry can build a ToolSpec from, validates it, and loads all enabled
capabilities from the DB into the live registry.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.security import CustomCapability
from app.security import registry

# Target kinds accepted by validate.by_kind — what a custom op may declare.
VALID_TARGET_KINDS = {
    "domain", "host", "ip", "url", "username", "email", "phone", "onion",
    "term", "hash", "port_spec",
}
VALID_POSTURES = {"passive", "active", "disruptive"}
VALID_SOURCES = {"apt", "kali", "pip", "go", "github", "gem", "builtin"}
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,48}$")
_OPKEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,60}$")


class CapabilityError(ValueError):
    pass


def build_entry(data: dict) -> dict:
    """Build a catalogue-shaped entry from a friendly capability definition.

    data = {
      name, purpose, binary, source, package, categories: [..],
      operations: [{key, title, description, posture, argv_template,
                    target_kind?, requires_authorization?, timeout?}]
    }
    """
    name = str(data.get("name") or "").strip().lower()
    if not _NAME_RE.match(name):
        raise CapabilityError("name must be lowercase letters/digits/._- (2–49 chars)")
    if name in registry.reserved_names():
        raise CapabilityError(f"'{name}' is a built-in tool name; choose another")

    source = str(data.get("source") or "apt").strip().lower()
    if source not in VALID_SOURCES:
        raise CapabilityError(f"source must be one of {sorted(VALID_SOURCES)}")

    ops_in = data.get("operations") or []
    if not isinstance(ops_in, list) or not ops_in:
        raise CapabilityError("at least one operation is required")

    reserved_ops = registry.reserved_op_keys()
    seen: set[str] = set()
    ops: list[dict] = []
    for op in ops_in:
        key = str(op.get("key") or "").strip().lower()
        if not _OPKEY_RE.match(key):
            raise CapabilityError(f"operation key '{key}' is invalid (e.g. amass.enum)")
        if key in reserved_ops:
            raise CapabilityError(f"operation key '{key}' already exists — pick a unique key")
        if key in seen:
            raise CapabilityError(f"duplicate operation key '{key}'")
        seen.add(key)

        posture = str(op.get("posture") or "passive").strip().lower()
        if posture not in VALID_POSTURES:
            raise CapabilityError(f"posture must be one of {sorted(VALID_POSTURES)}")

        tokens = [t for t in str(op.get("argv_template") or "").split() if t]
        target = None
        tk = str(op.get("target_kind") or "").strip().lower()
        if tk:
            if tk not in VALID_TARGET_KINDS:
                raise CapabilityError(f"target_kind must be one of {sorted(VALID_TARGET_KINDS)}")
            target = {"name": "target", "kind": tk}
            if "{target}" not in tokens:
                tokens.append("{target}")
        elif "{target}" in tokens:
            raise CapabilityError(f"op '{key}' uses {{target}} but no target_kind is set")

        timeout = op.get("timeout")
        ops.append({
            "key": key,
            "title": str(op.get("title") or key)[:120],
            "desc": str(op.get("description") or "")[:500],
            "posture": posture,
            "template": tokens,
            "auth": bool(op.get("requires_authorization")),
            "timeout": int(timeout) if timeout else None,
            "target": target,
        })

    return {
        "name": name,
        "purpose": str(data.get("purpose") or "")[:500],
        "package": str(data.get("package") or "").strip(),
        "source": source,
        "categories": [str(c).strip() for c in (data.get("categories") or []) if str(c).strip()],
        "binary": str(data.get("binary") or "").strip(),
        "root": False,
        "ops": ops,
    }


async def _enabled_entries(session: AsyncSession) -> list[dict]:
    rows = (
        await session.execute(
            select(CustomCapability).where(CustomCapability.enabled == True)  # noqa: E712
        )
    ).scalars().all()
    return [r.entry for r in rows if r.entry]


async def reload_registry(session: AsyncSession) -> int:
    """Load all enabled custom capabilities into the live registry. Returns the
    count loaded. Also invalidates the orchestrator's catalogue cache."""
    entries = await _enabled_entries(session)
    registry.set_custom_tools(entries)
    try:
        from app.security import orchestrator
        orchestrator._CATALOGUE_CACHE = None  # force rebuild on next turn
    except Exception:  # noqa: BLE001
        pass
    return len(entries)
