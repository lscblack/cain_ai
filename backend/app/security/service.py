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
from app.security import registry, targets
from app.security.executor import ExecResult, run_argv
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


async def run_operation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    op_key: str,
    params: dict,
    conversation_id: uuid.UUID | None = None,
) -> dict:
    found = registry.get_operation(op_key)
    if not found:
        return {"ok": False, "status": "error", "error": f"unknown operation: {op_key}"}
    tool, op = found
    params = params or {}
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
                argv, timeout=s.tool_exec_timeout_s, max_bytes=s.tool_output_max_bytes, stdin=stdin
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
