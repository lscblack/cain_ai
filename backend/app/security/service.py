"""Central tool-operation service.

One entry point — :func:`run_operation` — used by both the direct API endpoint
and the model orchestrator. It enforces, in order:

1. operation exists
2. tool installed on the real host (else: blocked + install hint)
3. authorization for ACTIVE operations (authorized-target list)
4. argument validation → argv (never a shell string)
5. per-operator rate limit
6. real execution (argv subprocess, or a Python adapter)
7. persistence (tool_executions) + audit log

It never raises for an expected refusal; it returns a structured dict with a
``status`` the model and UI can reason about.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.models.security import ToolExecution
from app.security import capabilities as caps_mod
from app.security import registry, targets
from app.security import osint_ops
from app.security import people_ops
from app.security import terminal
from app.security import web
from app.security import workspace as ws
from app.security.capabilities import SHELL_OP_KEY
from app.security.osint_ops import INV_OP_KEYS
from app.security.web import MAPS_FIND_OP_KEY, WEB_OPEN_OP_KEY, WEB_SEARCH_OP_KEY
from app.security.workspace import LIST_OP_KEY, WRITE_OP_KEY
from app.security.executor import ExecResult, display_argv, run_argv, run_shell

# Query a registered external data endpoint (the operator's own databases).
DATA_LOOKUP_OP_KEY = "data.lookup"
# Local-first identity resolution (saved DB → endpoint fallback → persist).
IDENTITY_LOOKUP_OP_KEY = "identity.lookup"
from app.security.redact import redact
from app.security.validate import ArgError


async def _rate_limited(session: AsyncSession, user_id: uuid.UUID) -> bool:
    s = get_settings()
    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    count = (
        await session.execute(
            select(func.count())
            .select_from(ToolExecution)
            .where(ToolExecution.user_id == user_id, ToolExecution.created_at >= since)
        )
    ).scalar_one()
    return count >= s.tool_rate_limit_per_min


async def _record(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    tool: str,
    operation: str,
    args: dict,
    target: str | None,
    posture: str | None,
    result: ExecResult,
) -> ToolExecution:
    row = ToolExecution(
        user_id=user_id,
        conversation_id=conversation_id,
        tool_name=tool,
        operation=operation,
        args=[f"{k}={redact(str(v))}" for k, v in args.items()],
        target=target,
        posture=posture,
        status=result.status,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.error,
    )
    session.add(row)
    await session.flush()
    return row


async def _auto_authorize(session: AsyncSession, user_id: uuid.UUID, host: str, op_key: str) -> None:
    """Auto-add a target to the operator's authorized list (audited). A domain
    entry covers its subdomains, so we don't create duplicate rows for those."""
    from app.database.models.audit import AuditLog
    from app.database.models.security import AuthorizedTarget

    if await targets.is_authorized(session, user_id, host):
        return  # already covered (e.g. by a parent domain)
    session.add(AuthorizedTarget(
        user_id=user_id, target=host, scope="active",
        note=f"auto-authorized on first use ({op_key})",
    ))
    session.add(AuditLog(
        actor_id=user_id, action="target.auto_authorize",
        detail={"target": host, "operation": op_key},
    ))
    await session.flush()


async def preview_operation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    op_key: str,
    params: dict,
) -> dict:
    """Resolve + validate a proposed tool call WITHOUT running it: same checks as
    :func:`run_operation` (installed, authorization) plus building its real argv,
    so the operator can see exactly what would execute before approving it."""
    params = params or {}

    # Raw terminal preview: show the exact command that would run.
    if op_key == SHELL_OP_KEY:
        caps = await caps_mod.get_capabilities(session, user_id)
        cmd = str(params.get("command") or "").strip()
        if not caps.shell_enabled:
            return {"ok": False, "status": "blocked", "reason": "shell_disabled",
                    "operation": op_key, "message": "Terminal access is disabled."}
        if not cmd:
            return {"ok": False, "status": "error", "error": "command required"}
        sudo = bool(params.get("sudo"))
        if sudo and not caps.shell_sudo:
            return {"ok": False, "status": "blocked", "reason": "sudo_disabled",
                    "operation": op_key, "message": "Root (sudo) commands are disabled."}
        preview = (f"pkexec bash -lc {cmd}" if sudo else f"bash -lc {cmd}")
        return {
            "ok": True, "tool": "shell", "operation": op_key,
            "posture": "shell-root" if sudo else "shell",
            "requires_authorization": False, "needs_authorization": False,
            "target": None, "preview": preview, "params": params,
        }

    if op_key in (WEB_SEARCH_OP_KEY, WEB_OPEN_OP_KEY, MAPS_FIND_OP_KEY):
        if op_key == WEB_SEARCH_OP_KEY:
            q = str(params.get("query") or params.get("q") or "").strip()
            preview = f"web search: {q[:120]}" if q else "web search"
            posture = "web"
        elif op_key == MAPS_FIND_OP_KEY:
            q = str(params.get("query") or params.get("q") or "").strip()
            preview = f"map lookup: {q[:120]}" if q else "map lookup"
            posture = "map"
        else:
            u = str(params.get("url") or params.get("u") or "").strip()
            preview = f"open page: {u[:160]}" if u else "open page"
            posture = "web"
        return {
            "ok": True, "tool": "web", "operation": op_key, "posture": posture,
            "requires_authorization": False, "needs_authorization": False,
            "target": None, "preview": preview, "params": params,
        }

    if op_key == IDENTITY_LOOKUP_OP_KEY:
        who = params.get("nid") or params.get("phone") or params.get("name") or ""
        return {
            "ok": True, "tool": "identity", "operation": op_key, "posture": "data",
            "requires_authorization": False, "needs_authorization": False, "target": str(who) or None,
            "preview": f"resolve identity (saved DB first): {who}", "params": params,
        }

    if op_key == DATA_LOOKUP_OP_KEY:
        slug = str(params.get("endpoint") or params.get("slug") or "").strip()
        detail = ", ".join(f"{k}={v}" for k, v in params.items() if k not in ("endpoint", "slug"))
        return {
            "ok": True, "tool": "data", "operation": op_key, "posture": "data",
            "requires_authorization": False, "needs_authorization": False, "target": slug or None,
            "preview": f"query data endpoint '{slug}'" + (f" ({detail})" if detail else ""),
            "params": params,
        }

    if op_key in INV_OP_KEYS:
        return {
            "ok": True, "tool": "investigation", "operation": op_key,
            "posture": "investigation", "requires_authorization": False,
            "needs_authorization": False, "target": None,
            "preview": osint_ops.preview(op_key, params), "params": params,
        }

    if op_key in people_ops.PEOPLE_OP_KEYS:
        return {
            "ok": True, "tool": "people", "operation": op_key, "posture": "investigation",
            "requires_authorization": False, "needs_authorization": False, "target": None,
            "preview": people_ops.preview(params), "params": params,
        }

    if op_key in (WRITE_OP_KEY, LIST_OP_KEY):
        if op_key == WRITE_OP_KEY:
            name = str(params.get("filename") or params.get("path") or "(unnamed)")
            size = len(str(params.get("content") or "").encode("utf-8"))
            preview = f"write {name} ({size} bytes) to workspace"
        else:
            preview = "list workspace files"
        return {
            "ok": True, "tool": "files", "operation": op_key, "posture": "file",
            "requires_authorization": False, "needs_authorization": False,
            "target": None, "preview": preview, "params": params,
        }

    found = registry.get_operation(op_key)
    if not found:
        return {"ok": False, "status": "error", "error": f"unknown operation: {op_key}"}
    tool, op = found
    target = str(params.get(op.target_param)) if op.target_param and params.get(op.target_param) else None

    disc = await registry.discover(tool)
    if not disc.installed:
        return {
            "ok": False, "status": "blocked", "reason": "tool_not_installed",
            "tool": tool.name, "operation": op_key,
            "message": f"'{tool.name}' is not installed (package: {tool.package}, source: {tool.source}).",
            "install_hint": {"package": tool.package, "source": tool.source},
        }

    needs_authorization = False
    if op.requires_authorization and target:
        from app.security.validate import ArgError as _ArgError
        from app.security.validate import target_host as _target_host

        try:
            norm_host = _target_host(target)
        except _ArgError as exc:
            return {"ok": False, "status": "error", "error": f"invalid target: {exc}"}
        target = norm_host
        needs_authorization = not await targets.is_authorized(session, user_id, target)

    if op.pyrun is not None:
        preview = f"(builtin) {tool.name}.{op.key}"
    else:
        try:
            argv = op.build_argv(disc.path, params)
        except ArgError as exc:
            return {"ok": False, "status": "error", "error": f"invalid argument: {exc}"}
        preview = display_argv(argv)

    return {
        "ok": True,
        "tool": tool.name,
        "operation": op_key,
        "posture": op.posture,
        "requires_authorization": op.requires_authorization,
        "needs_authorization": needs_authorization,
        "target": target,
        "preview": preview,
        "params": params,
    }


async def _run_shell_op(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    params: dict,
    conversation_id: uuid.UUID | None,
    caps,
) -> dict:
    """Execute the raw terminal operation (``shell.run``). Reached only from
    run_operation. Gated by caps.shell_enabled; rate-limited, recorded, and
    audited exactly like any catalogue tool. The command runs through
    ``bash -lc`` with the operator's real environment."""
    if not caps.shell_enabled:
        return {
            "ok": False, "status": "blocked", "reason": "shell_disabled",
            "operation": SHELL_OP_KEY,
            "message": ("Terminal access is disabled for KAI. Enable 'terminal "
                        "access' in the Capabilities panel to allow shell commands."),
        }
    command = str(params.get("command") or "").strip()
    if not command:
        return {"ok": False, "status": "error", "error": "command required"}

    sudo = bool(params.get("sudo"))
    if sudo and not caps.shell_sudo:
        return {
            "ok": False, "status": "blocked", "reason": "sudo_disabled",
            "operation": SHELL_OP_KEY,
            "message": ("Privileged (root) commands are disabled. Enable 'root "
                        "commands (sudo)' in the Capabilities panel to allow them."),
        }

    if await _rate_limited(session, user_id):
        return {"ok": False, "status": "blocked", "reason": "rate_limited",
                "message": "Tool execution rate limit reached; try again shortly."}

    s = get_settings()
    interactive = bool(params.get("interactive"))
    cwd = ws.session_cwd(user_id, conversation_id)  # initial dir for a new session
    running = False
    posture = "shell-root" if sudo else "shell"

    if sudo:
        # Privileged commands run one-shot via pkexec (desktop password prompt),
        # not in the persistent session.
        res = await run_shell(
            command, sudo=True, timeout=s.tool_exec_timeout_s,
            max_bytes=s.tool_output_max_bytes, cwd=cwd,
        )
    else:
        # Persistent interactive terminal per conversation — cwd/env persist and
        # the model can type into running programs (interactive=True sends input).
        key = str(conversation_id) if conversation_id else f"u:{user_id}"
        try:
            r = await terminal.exec_in_session(key, command, cwd=cwd, interactive=interactive)
        except Exception as exc:  # noqa: BLE001 — surface terminal failures as a result
            r = {"output": f"(terminal error: {exc})", "exit_code": None,
                 "finished": True, "running": False, "dead": True}
        running = bool(r.get("running"))
        ec = r.get("exit_code")
        dead = bool(r.get("dead"))
        st = "error" if dead else ("ok" if (running or ec in (0, None)) else "error")
        res = ExecResult(
            argv=["bash", "-lc", command], status=st, exit_code=ec,
            stdout=redact(r.get("output", "") or "")[: s.tool_output_max_bytes], stderr="",
            error=None if st == "ok" else (f"exit {ec}" if ec is not None else "terminal error"),
        )

    row = await _record(
        session, user_id=user_id, conversation_id=conversation_id, tool="shell",
        operation=SHELL_OP_KEY, args={"command": command, "sudo": sudo, "interactive": interactive},
        target=None, posture=posture, result=res,
    )

    from app.database.models.audit import AuditLog

    session.add(AuditLog(
        actor_id=user_id,
        action="tool.shell",
        detail={"operation": SHELL_OP_KEY, "status": res.status, "sudo": sudo,
                "running": running, "execution_id": str(row.id), "command": redact(command)[:500]},
    ))
    await session.flush()

    # Register any files the command created in the workspace so they show up as
    # downloadable assets in the chat (the shell runs with cwd = workspace).
    new_files: list[dict] = []
    try:
        new_files = (await ws.list_files(
            session, user_id=user_id, conversation_id=conversation_id,
        )).get("files", [])
    except Exception:  # noqa: BLE001
        pass

    out = res.to_dict()
    out.update({
        "ok": res.status == "ok",
        "execution_id": str(row.id),
        "tool": "shell",
        "operation": SHELL_OP_KEY,
        "posture": posture,
        "target": None,
    })
    if new_files:
        out["files"] = new_files  # chat renders download chips for these
    if running:
        out["running"] = True
        out["message"] = (
            "The command is still running or a program is waiting for input. To type "
            "the next line (e.g. a password or a REPL command), call shell.run again "
            'with "interactive": true, e.g. '
            '{"action":"tool","operation":"shell.run","params":{"command":"<input>","interactive":true}}. '
            'Send an empty command with "interactive": true to just read more output.'
        )
    return out


async def _run_web_op(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    op_key: str,
    params: dict,
    conversation_id: uuid.UUID | None,
) -> dict:
    """Execute a web browsing operation (``web.search`` / ``web.open``).

    Benign network I/O (read-only HTTP GET/POST to search + fetch), so it is not
    gated by ``tools_enabled`` — like the file ops. Still rate-limited, recorded
    and audited."""
    if await _rate_limited(session, user_id):
        return {"ok": False, "status": "blocked", "reason": "rate_limited",
                "message": "Tool execution rate limit reached; try again shortly."}

    if op_key == WEB_SEARCH_OP_KEY:
        query = str(params.get("query") or params.get("q") or "")
        data = await web.search(query, max_results=params.get("max_results", 8))
        args = {"query": query}
        target = query
        posture = "web"
    elif op_key == MAPS_FIND_OP_KEY:
        query = str(params.get("query") or params.get("q") or "")
        data = await web.geocode(query, limit=params.get("limit", 10))
        args = {"query": query}
        target = query
        posture = "map"
    else:  # WEB_OPEN_OP_KEY
        url = str(params.get("url") or params.get("u") or "")
        data = await web.open_url(url)
        args = {"url": url}
        target = url
        posture = "web"

    res = ExecResult(
        argv=[f"(builtin:{op_key})"],
        status="ok" if data.get("ok") else "error",
        error=None if data.get("ok") else str(data.get("error") or "web error"),
        extra=data,
    )
    row = await _record(
        session, user_id=user_id, conversation_id=conversation_id, tool="web",
        operation=op_key, args=args, target=None, posture=posture, result=res,
    )
    from app.database.models.audit import AuditLog

    session.add(AuditLog(
        actor_id=user_id, action="tool.web",
        detail={"operation": op_key, "status": res.status,
                "execution_id": str(row.id), "target": redact(target)[:300]},
    ))
    await session.flush()

    out = dict(data)
    out.update({
        "ok": data.get("ok", False), "execution_id": str(row.id),
        "tool": "web", "operation": op_key, "posture": posture,
    })
    return out


async def _run_data_lookup(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    params: dict,
    conversation_id: uuid.UUID | None,
) -> dict:
    """Call a registered external data endpoint (the operator's own database).

    params: ``{"endpoint": "<slug>", "params": {...}}`` — or pass ``nid`` /
    ``phone`` / ``upi`` directly. Benign read against the operator's own system;
    rate-limited, recorded and audited. Base64 image fields are summarised, not
    returned, to keep the model's context small."""
    from app.enrich import endpoints as ep_mod
    from app.enrich.client import call_endpoint

    slug = str(params.get("endpoint") or params.get("slug") or "").strip()
    if not slug:
        return {"ok": False, "status": "error", "operation": DATA_LOOKUP_OP_KEY, "tool": "data",
                "error": "endpoint slug is required (use data.list_endpoints-style knowledge)"}
    call_params = params.get("params") if isinstance(params.get("params"), dict) else {
        k: params[k] for k in ("nid", "phone", "upi") if params.get(k)
    }
    endpoint = await ep_mod.get_by_slug(session, user_id, slug)
    if endpoint is None:
        return {"ok": False, "status": "error", "operation": DATA_LOOKUP_OP_KEY, "tool": "data",
                "error": f"no endpoint registered with slug '{slug}'"}
    if not endpoint.enabled:
        return {"ok": False, "status": "blocked", "operation": DATA_LOOKUP_OP_KEY, "tool": "data",
                "error": f"endpoint '{slug}' is disabled"}

    if await _rate_limited(session, user_id):
        return {"ok": False, "status": "blocked", "reason": "rate_limited",
                "message": "Tool execution rate limit reached; try again shortly."}

    res = await call_endpoint(endpoint, call_params)
    data = res.data
    if isinstance(data, dict) and endpoint.image_keys:
        data = {k: (f"<image {len(v)} chars>" if k in endpoint.image_keys and isinstance(v, str) else v)
                for k, v in data.items()}

    exec_res = ExecResult(
        argv=[f"(data:{slug})"], status="ok" if res.ok else "error",
        error=None if res.ok else str(res.error), extra={"data": data, "images_found": sorted(res.images.keys())},
    )
    row = await _record(
        session, user_id=user_id, conversation_id=conversation_id, tool="data",
        operation=DATA_LOOKUP_OP_KEY, args={"endpoint": slug, **call_params},
        target=slug, posture="data", result=exec_res,
    )
    from app.database.models.audit import AuditLog

    session.add(AuditLog(actor_id=user_id, action="tool.data_lookup",
                         detail={"endpoint": slug, "status": exec_res.status, "execution_id": str(row.id)}))
    await session.flush()
    out = exec_res.to_dict()
    out.update({"ok": res.ok, "execution_id": str(row.id), "tool": "data",
                "operation": DATA_LOOKUP_OP_KEY, "posture": "data", "endpoint": slug})
    return out


async def _run_identity_lookup(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    params: dict,
    conversation_id: uuid.UUID | None,
) -> dict:
    """Local-first resolve of a NID / phone / name: searches the saved DB and
    only falls back to the external endpoints when missing, persisting new
    records. Rate-limited, recorded, audited."""
    from app.enrich.lookup import resolve_identity

    nid = str(params.get("nid") or "").strip() or None
    phone = str(params.get("phone") or "").strip() or None
    name = str(params.get("name") or "").strip() or None
    if not (nid or phone or name):
        return {"ok": False, "status": "error", "operation": IDENTITY_LOOKUP_OP_KEY, "tool": "identity",
                "error": "provide nid, phone, or name"}

    if await _rate_limited(session, user_id):
        return {"ok": False, "status": "blocked", "reason": "rate_limited",
                "message": "Tool execution rate limit reached; try again shortly."}

    data = await resolve_identity(session, user_id, nid=nid, phone=phone, name=name)
    exec_res = ExecResult(
        argv=[f"(identity:{nid or phone or name})"],
        status="ok" if data.get("ok") else "error",
        error=None if data.get("ok") else str(data.get("error")), extra=data,
    )
    row = await _record(
        session, user_id=user_id, conversation_id=conversation_id, tool="identity",
        operation=IDENTITY_LOOKUP_OP_KEY, args={k: v for k, v in params.items() if v},
        target=(nid or phone or name), posture="data", result=exec_res,
    )
    from app.database.models.audit import AuditLog

    session.add(AuditLog(actor_id=user_id, action="tool.identity_lookup",
                         detail={"source": data.get("source"), "found": data.get("found"),
                                 "execution_id": str(row.id)}))
    await session.flush()
    out = exec_res.to_dict()
    out.update({"ok": data.get("ok", False), "execution_id": str(row.id),
                "tool": "identity", "operation": IDENTITY_LOOKUP_OP_KEY, "posture": "data"})
    return out


async def run_operation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    op_key: str,
    params: dict,
    conversation_id: uuid.UUID | None = None,
) -> dict:
    params = params or {}

    # ── capabilities gate (operator-controlled) ──────────────────────────── #
    caps = await caps_mod.get_capabilities(session, user_id)

    # Local-first identity resolution (saved DB → endpoint fallback → persist).
    if op_key == IDENTITY_LOOKUP_OP_KEY:
        return await _run_identity_lookup(
            session, user_id=user_id, params=params, conversation_id=conversation_id,
        )

    # External data endpoints (the operator's own databases). Benign read —
    # not gated by tools_enabled; rate-limited + audited like the web ops.
    if op_key == DATA_LOOKUP_OP_KEY:
        return await _run_data_lookup(
            session, user_id=user_id, params=params, conversation_id=conversation_id,
        )

    # Web browsing: read-only HTTP (search + page fetch + map geocode). Benign —
    # not gated by tools_enabled, same as the file ops. Rate-limited + audited.
    if op_key in (WEB_SEARCH_OP_KEY, WEB_OPEN_OP_KEY, MAPS_FIND_OP_KEY):
        return await _run_web_op(
            session, user_id=user_id, op_key=op_key, params=params,
            conversation_id=conversation_id,
        )

    # Investigation casework: KAI creates/reads cases + records entities/evidence
    # itself, via the same repositories as the HTTP API. Benign DB I/O on the
    # operator's own cases — not gated by tools_enabled. Rate-limited + audited.
    if op_key in INV_OP_KEYS:
        if await _rate_limited(session, user_id):
            return {"ok": False, "status": "blocked", "reason": "rate_limited",
                    "message": "Tool execution rate limit reached; try again shortly."}
        data = await osint_ops.run_investigation_op(
            session, user_id=user_id, op_key=op_key, params=params,
        )
        from app.database.models.audit import AuditLog

        session.add(AuditLog(
            actor_id=user_id, action="tool.investigation",
            detail={"operation": op_key, "status": "ok" if data.get("ok") else "error"}))
        await session.flush()
        data.setdefault("tool", "investigation")
        data.setdefault("posture", "investigation")
        data.setdefault("operation", op_key)
        return data

    if op_key in people_ops.PEOPLE_OP_KEYS:
        if await _rate_limited(session, user_id):
            return {"ok": False, "status": "blocked", "reason": "rate_limited",
                    "message": "Tool execution rate limit reached; try again shortly."}
        data = await people_ops.run_people_op(
            session, user_id=user_id, op_key=op_key, params=params,
        )
        data.setdefault("tool", "people")
        data.setdefault("posture", "investigation")
        data.setdefault("operation", op_key)
        return data

    # Raw terminal: not a catalogue tool. Handled here, gated by shell_enabled.
    if op_key == SHELL_OP_KEY:
        return await _run_shell_op(
            session, user_id=user_id, params=params,
            conversation_id=conversation_id, caps=caps,
        )

    # File output: KAI writes/lists files in the operator's workspace so they
    # can be downloaded from the chat. Benign I/O — not gated by tools_enabled.
    if op_key == WRITE_OP_KEY:
        return await ws.write_file(
            session, user_id=user_id, conversation_id=conversation_id,
            filename=str(params.get("filename") or params.get("path") or ""),
            content=str(params.get("content") or ""),
        )
    if op_key == LIST_OP_KEY:
        return await ws.list_files(
            session, user_id=user_id, conversation_id=conversation_id,
        )

    found = registry.get_operation(op_key)
    if not found:
        return {"ok": False, "status": "error", "error": f"unknown operation: {op_key}"}
    tool, op = found

    if not caps.tools_enabled:
        return {
            "ok": False, "status": "blocked", "reason": "tools_disabled",
            "operation": op_key,
            "message": ("Tool execution is disabled for KAI. Enable it in the "
                        "Capabilities panel to let KAI run installed tools."),
        }
    target = str(params.get(op.target_param)) if op.target_param and params.get(op.target_param) else None

    # 1. availability
    disc = await registry.discover(tool)
    if not disc.installed:
        return {
            "ok": False,
            "status": "blocked",
            "reason": "tool_not_installed",
            "tool": tool.name,
            "operation": op_key,
            "message": (
                f"'{tool.name}' is not installed. Request installation of the "
                f"'{tool.package}' package (source: {tool.source}) via the "
                f"installation-approval workflow."
            ),
            "install_hint": {"package": tool.package, "source": tool.source},
        }

    # 2. authorization for ACTIVE ops
    if op.requires_authorization:
        if not target:
            return {"ok": False, "status": "error", "error": "target required"}
        # Normalize URL/host:port → bare host; reject anything unparseable.
        from app.security.validate import ArgError as _ArgError
        from app.security.validate import target_host as _target_host

        try:
            norm_host = _target_host(target)
        except _ArgError as exc:
            return {"ok": False, "status": "error", "error": f"invalid target: {exc}"}

        if not await targets.is_authorized(session, user_id, target):
            if get_settings().tool_auto_authorize_targets:
                await _auto_authorize(session, user_id, norm_host, op_key)
            else:
                res = ExecResult(argv=[], status="error", error="target not authorized")
                await _record(
                    session, user_id=user_id, conversation_id=conversation_id, tool=tool.name,
                    operation=op_key, args=params, target=norm_host, posture=op.posture, result=res,
                )
                return {
                    "ok": False,
                    "status": "denied",
                    "reason": "target_not_authorized",
                    "tool": tool.name,
                    "operation": op_key,
                    "target": norm_host,
                    "message": (
                        f"'{norm_host}' is not on your authorized-targets list. Active "
                        f"assessment is refused until you authorize it explicitly."
                    ),
                }

    # 3. rate limit
    if await _rate_limited(session, user_id):
        return {"ok": False, "status": "blocked", "reason": "rate_limited",
                "message": "Tool execution rate limit reached; try again shortly."}

    # 4. build + execute
    s = get_settings()
    try:
        if op.pyrun is not None:
            try:
                data = await op.pyrun(params)
                res = ExecResult(argv=[f"(builtin:{tool.name})"], status="ok", extra=data)
            except (ValueError, RuntimeError) as exc:
                res = ExecResult(argv=[f"(builtin:{tool.name})"], status="error", error=str(exc))
        else:
            argv = op.build_argv(disc.path, params)  # may raise ArgError
            stdin = b"" if tool.name == "openssl" else None
            res = await run_argv(
                argv, timeout=op.timeout_s or s.tool_exec_timeout_s,
                max_bytes=s.tool_output_max_bytes, stdin=stdin
            )
    except ArgError as exc:
        res = ExecResult(argv=[], status="error", error=f"invalid argument: {exc}")

    row = await _record(
        session, user_id=user_id, conversation_id=conversation_id, tool=tool.name,
        operation=op_key, args=params, target=target, posture=op.posture, result=res,
    )

    # 5. audit
    from app.database.models.audit import AuditLog

    session.add(AuditLog(
        actor_id=user_id,
        action="tool.execute",
        detail={"operation": op_key, "tool": tool.name, "target": target,
                "posture": op.posture, "status": res.status, "execution_id": str(row.id)},
    ))
    await session.flush()

    out = res.to_dict()
    out.update({
        "ok": res.status == "ok",
        "execution_id": str(row.id),
        "tool": tool.name,
        "operation": op_key,
        "posture": op.posture,
        "target": target,
    })
    return out
