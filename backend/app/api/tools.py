"""Security tooling API: inventory, execution, targets, findings, installs.

All endpoints require an authenticated operator. Tool execution goes through
the hardened service (argv only, auth checks, limits, audit). Installs follow
a strict approval workflow; the model/UI can request, only an operator approves,
and nothing is marked installed until it verifies on the real host.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_operator
from app.database.models.audit import AuditLog
from app.database.models.security import (
    AuthorizedTarget,
    InstallRequest,
    SecurityFinding,
    ToolExecution,
    ToolVerification,
)
from app.database.models.user import User
from app.database.session import get_session
from app.security import install as install_mod
from app.security import registry, service
from app.security import validate as V

router = APIRouter(prefix="/tools", tags=["tools"])


# ───────────────────────── inventory ────────────────────────────────── #
@router.get("/inventory")
async def inventory(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Live tool inventory from the real host; also persists verification rows."""
    import asyncio

    now = datetime.now(timezone.utc).isoformat()
    tools = list(registry.ALL_TOOLS)
    discs = await asyncio.gather(*(registry.discover(t) for t in tools))
    avail = await install_mod.apt_availability([t.package for t in tools if t.source == "apt" and t.package])
    tools_out = []
    for tool, disc in zip(tools, discs):
        # upsert verification record
        row = (
            await session.execute(
                select(ToolVerification).where(ToolVerification.tool_name == tool.name)
            )
        ).scalars().first()
        if row is None:
            row = ToolVerification(tool_name=tool.name)
            session.add(row)
        row.installed = disc.installed
        row.path = disc.path
        row.version = disc.version
        row.verified_at = now
        tools_out.append({
            "name": tool.name,
            "purpose": tool.purpose,
            "package": tool.package,
            "source": tool.source,
            "apt_available": avail.get(tool.package) if tool.source == "apt" else None,
            "categories": list(tool.categories),
            "installed": disc.installed,
            "path": disc.path,
            "version": disc.version,
            "operations": [
                {
                    "key": op.key, "title": op.title, "description": op.description,
                    "posture": op.posture, "requires_authorization": op.requires_authorization,
                    "needs_root": op.needs_root,
                    "params": [
                        {"name": p.name, "kind": p.kind, "required": p.required,
                         "default": p.default, "help": p.help}
                        for p in op.params
                    ],
                }
                for op in tool.operations
            ],
        })
    await session.flush()
    installed = sum(1 for t in tools_out if t["installed"])
    return {"tools": tools_out, "counts": {"total": len(tools_out), "installed": installed,
                                           "missing": len(tools_out) - installed},
            "verified_at": now}


@router.post("/verify/{tool_name}")
async def verify_tool(
    tool_name: str,
    operator: User = Depends(get_current_operator),
) -> dict:
    return await install_mod.verify_tool(tool_name)


# ───────────────────────── direct execution ─────────────────────────── #
class ExecuteBody(BaseModel):
    operation: str
    params: dict = Field(default_factory=dict)
    conversation_id: uuid.UUID | None = None


@router.post("/execute")
async def execute(
    body: ExecuteBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await service.run_operation(
        session, user_id=operator.id, op_key=body.operation,
        params=body.params, conversation_id=body.conversation_id,
    )


class SweepBody(BaseModel):
    domain: str | None = None
    host: str | None = None
    url: str | None = None
    email: str | None = None
    username: str | None = None
    phone: str | None = None
    ip: str | None = None
    identifiers: list[dict] = Field(default_factory=list)  # [{kind,value},...]
    conversation_id: uuid.UUID | None = None


@router.post("/sweep")
async def osint_sweep(
    body: SweepBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Run every applicable INSTALLED passive OSINT tool over the given
    identifiers (a person search's email/username/phone, a domain, a host…)."""
    from app.security import sweep

    ids: list[tuple[str, str]] = []
    for kind in ("domain", "host", "url", "email", "username", "phone", "ip"):
        v = getattr(body, kind)
        if v:
            ids.append((kind, v.strip()))
    for item in body.identifiers:
        k, v = item.get("kind"), item.get("value")
        if k and v:
            ids.append((str(k), str(v).strip()))
    if not ids:
        raise HTTPException(status_code=422, detail="at least one identifier required")
    return await sweep.run_osint_sweep(
        session, user_id=operator.id, identifiers=ids, conversation_id=body.conversation_id,
    )


@router.get("/executions")
async def executions(
    limit: int = 50,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await session.execute(
            select(ToolExecution)
            .where(ToolExecution.user_id == operator.id)
            .order_by(ToolExecution.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id), "tool": r.tool_name, "operation": r.operation,
            "args": r.args, "target": r.target, "posture": r.posture, "status": r.status,
            "exit_code": r.exit_code, "duration_ms": r.duration_ms,
            "stdout": r.stdout[:8000], "stderr": r.stderr[:4000], "error": r.error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# ───────────────────────── authorized targets ───────────────────────── #
class TargetBody(BaseModel):
    target: str
    scope: str = "active"
    note: str = ""


@router.get("/targets")
async def list_targets(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await session.execute(
            select(AuthorizedTarget).where(AuthorizedTarget.user_id == operator.id)
            .order_by(AuthorizedTarget.created_at.desc())
        )
    ).scalars().all()
    return [
        {"id": str(r.id), "target": r.target, "scope": r.scope, "note": r.note,
         "active": r.active, "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


@router.post("/targets", status_code=201)
async def add_target(
    body: TargetBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        norm = V.target_or_cidr(body.target)
    except V.ArgError as exc:
        raise HTTPException(status_code=422, detail=f"invalid target: {exc}")
    row = AuthorizedTarget(user_id=operator.id, target=norm, scope=body.scope, note=body.note[:500])
    session.add(row)
    session.add(AuditLog(actor_id=operator.id, action="target.authorize",
                         detail={"target": norm, "scope": body.scope}))
    await session.flush()
    await session.refresh(row)
    return {"id": str(row.id), "target": row.target, "scope": row.scope, "note": row.note, "active": row.active}


@router.delete("/targets/{target_id}", status_code=204)
async def remove_target(
    target_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.get(AuthorizedTarget, target_id)
    if row is None or row.user_id != operator.id:
        raise HTTPException(status_code=404, detail="target_not_found")
    await session.delete(row)
    session.add(AuditLog(actor_id=operator.id, action="target.revoke", detail={"target": row.target}))
    await session.flush()


# ───────────────────────── findings ─────────────────────────────────── #
@router.get("/findings")
async def findings(
    limit: int = 100,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await session.execute(
            select(SecurityFinding).where(SecurityFinding.user_id == operator.id)
            .order_by(SecurityFinding.created_at.desc()).limit(max(1, min(limit, 300)))
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id), "title": r.title, "description": r.description,
            "severity": r.severity, "confidence": r.confidence, "status": r.status,
            "asset": r.asset, "tool": r.tool, "evidence": r.evidence, "impact": r.impact,
            "remediation": r.remediation, "validation": r.validation, "limitations": r.limitations,
            "conversation_id": str(r.conversation_id) if r.conversation_id else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# ───────────────────────── install workflow ─────────────────────────── #
class InstallPlanBody(BaseModel):
    package: str | None = None
    capability: str | None = None  # a tool name whose package we should install


class InstallRequestBody(BaseModel):
    package: str | None = None
    capability: str | None = None
    reason: str = ""


def _resolve_package(package: str | None, capability: str | None) -> tuple[str, str | None]:
    if capability:
        tool = registry.get_tool(capability)
        if tool and tool.package:
            return tool.package, capability
    if package:
        return package, capability
    raise HTTPException(status_code=422, detail="package or capability required")


@router.post("/install/plan")
async def install_plan(
    body: InstallPlanBody,
    operator: User = Depends(get_current_operator),
) -> dict:
    pkg, _cap = _resolve_package(body.package, body.capability)
    return await install_mod.plan_install(pkg)


@router.post("/install/requests", status_code=201)
async def create_install_request(
    body: InstallRequestBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    pkg, cap = _resolve_package(body.package, body.capability)
    try:
        pkg = V.package_name(pkg)
    except V.ArgError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    plan = await install_mod.plan_install(pkg)
    req = InstallRequest(
        user_id=operator.id, capability=cap, package=pkg, source="apt",
        reason=body.reason[:1000], needs_root=True, status="pending",
    )
    session.add(req)
    session.add(AuditLog(actor_id=operator.id, action="install.request", detail={"package": pkg}))
    await session.flush()
    await session.refresh(req)
    return {"request": _install_out(req), "plan": plan}


@router.get("/install/requests")
async def list_install_requests(
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await session.execute(
            select(InstallRequest).where(InstallRequest.user_id == operator.id)
            .order_by(InstallRequest.created_at.desc())
        )
    ).scalars().all()
    return [_install_out(r) for r in rows]


@router.post("/install/requests/{req_id}/reject")
async def reject_install(
    req_id: uuid.UUID,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    req = await _get_install_or_404(req_id, operator.id, session)
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"request already {req.status}")
    req.status = "rejected"
    req.decided_by = operator.id
    req.decided_at = datetime.now(timezone.utc).isoformat()
    session.add(req)
    session.add(AuditLog(actor_id=operator.id, action="install.reject", detail={"package": req.package}))
    await session.flush()
    return _install_out(req)


@router.post("/install/requests/{req_id}/approve")
async def approve_install(
    req_id: uuid.UUID,
    reinstall: bool = False,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Approve and perform the install, then verify. Reports the REAL outcome —
    a tool is only marked installed if verification succeeds."""
    req = await _get_install_or_404(req_id, operator.id, session)
    if req.status not in ("pending", "approved", "failed"):
        raise HTTPException(status_code=409, detail=f"request already {req.status}")
    return await _execute_install(req, operator, session, reinstall)


async def _execute_install(
    req: InstallRequest, operator: User, session: AsyncSession, reinstall: bool,
) -> dict:
    req.status = "installing"
    req.decided_by = operator.id
    req.decided_at = datetime.now(timezone.utc).isoformat()
    session.add(req)
    session.add(AuditLog(actor_id=operator.id, action="install.approve",
                         detail={"package": req.package, "reinstall": reinstall}))
    await session.flush()
    await session.commit()

    outcome = await install_mod.perform_install(req.package, reinstall=reinstall)
    # Verify against the real host regardless of reported exit code.
    verify_name = req.capability or req.package
    verify = await install_mod.verify_tool(verify_name)

    req.log = outcome.get("log", "")[:20000]
    if outcome.get("ok") and verify.get("installed"):
        req.status = "installed"
        req.installed_version = verify.get("version")
    else:
        req.status = "failed"
    session.add(req)
    session.add(AuditLog(actor_id=operator.id, action="install.result",
                         detail={"package": req.package, "status": req.status,
                                 "reinstall": reinstall, "verified": verify.get("installed")}))
    await session.flush()
    return {"request": _install_out(req), "outcome": {k: outcome.get(k) for k in
            ("ok", "status", "exit_code", "error", "sudo_needs_password")}, "verify": verify}


class InstallNowBody(BaseModel):
    package: str | None = None
    capability: str | None = None
    reinstall: bool = False
    reason: str = ""


def _apt_only(capability: str | None) -> None:
    tool = registry.get_tool(capability) if capability else None
    if tool is not None and tool.source != "apt":
        raise HTTPException(
            status_code=422,
            detail=(f"'{tool.name}' comes from {tool.source}, not apt — KAI only installs apt "
                    f"packages. Install it manually, then press refresh."),
        )


@router.post("/install/now")
async def install_now(
    body: InstallNowBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """One-click install / reinstall. The operator pressing the button IS the
    approval; the request is still recorded and audited like any other."""
    _apt_only(body.capability)
    pkg, cap = _resolve_package(body.package, body.capability)
    try:
        pkg = V.package_name(pkg)
    except V.ArgError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    plan = await install_mod.plan_install(pkg)
    if not plan.get("available") and not plan.get("already_installed"):
        raise HTTPException(
            status_code=422,
            detail=f"package '{pkg}' is not available in the configured apt sources",
        )
    if plan.get("already_installed") and not body.reinstall:
        verify = await install_mod.verify_tool(cap or pkg)
        return {"request": None, "outcome": {"ok": True, "status": "already_installed"},
                "verify": verify, "plan": plan}
    req = InstallRequest(
        user_id=operator.id, capability=cap, package=pkg, source="apt",
        reason=(body.reason or ("reinstall" if body.reinstall else "install now"))[:1000],
        needs_root=True, status="pending",
    )
    session.add(req)
    session.add(AuditLog(actor_id=operator.id, action="install.request", detail={"package": pkg}))
    await session.flush()
    await session.refresh(req)
    out = await _execute_install(req, operator, session, body.reinstall)
    out["plan"] = plan
    return out


class InstallBatchBody(BaseModel):
    capabilities: list[str] = Field(min_length=1, max_length=150)
    reinstall: bool = False


@router.post("/install/batch")
async def install_batch(
    body: InstallBatchBody,
    operator: User = Depends(get_current_operator),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Install many tools with ONE privileged apt call (one polkit prompt).
    Non-apt tools and packages missing from apt are skipped and reported."""
    import asyncio

    skipped: list[dict] = []
    wanted: dict[str, list[str]] = {}  # package -> tool names
    for cap in dict.fromkeys(body.capabilities):
        tool = registry.get_tool(cap)
        if tool is None or not tool.package:
            skipped.append({"tool": cap, "reason": "unknown tool or no package"})
        elif tool.source != "apt":
            skipped.append({"tool": cap, "reason": f"source is {tool.source}, not apt"})
        else:
            wanted.setdefault(tool.package, []).append(cap)

    plans = dict(zip(wanted, await asyncio.gather(*(install_mod.plan_install(p) for p in wanted))))
    todo: list[str] = []
    for pkg, plan in plans.items():
        if not plan.get("ok"):
            skipped.extend({"tool": t, "reason": plan.get("error", "invalid package")} for t in wanted[pkg])
        elif plan.get("already_installed") and not body.reinstall:
            skipped.extend({"tool": t, "reason": "already installed"} for t in wanted[pkg])
        elif not plan.get("available") and not plan.get("already_installed"):
            skipped.extend({"tool": t, "reason": "not available in apt sources"} for t in wanted[pkg])
        else:
            todo.append(pkg)

    if not todo:
        return {"installed": [], "failed": [], "skipped": skipped, "outcome": None}

    session.add(AuditLog(actor_id=operator.id, action="install.batch",
                         detail={"packages": todo, "reinstall": body.reinstall}))
    await session.flush()
    await session.commit()
    outcome = await install_mod.perform_install_many(todo, reinstall=body.reinstall, timeout=3600)

    installed, failed = [], []
    for pkg in todo:
        for name in wanted[pkg]:
            verify = await install_mod.verify_tool(name)
            ok = bool(outcome.get("ok") and verify.get("installed"))
            req = InstallRequest(
                user_id=operator.id, capability=name, package=pkg, source="apt",
                reason="batch reinstall" if body.reinstall else "batch install",
                needs_root=True, status="installed" if ok else "failed",
                installed_version=verify.get("version") if ok else None,
                log=(outcome.get("log") or "")[-4000:],
                decided_by=operator.id, decided_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(req)
            (installed if ok else failed).append({"tool": name, "package": pkg,
                                                  "version": verify.get("version")})
    session.add(AuditLog(actor_id=operator.id, action="install.batch.result",
                         detail={"installed": len(installed), "failed": len(failed)}))
    await session.flush()
    return {"installed": installed, "failed": failed, "skipped": skipped,
            "outcome": {k: outcome.get(k) for k in ("ok", "status", "exit_code", "error",
                                                    "sudo_needs_password")}}


def _install_out(r: InstallRequest) -> dict:
    return {
        "id": str(r.id), "package": r.package, "capability": r.capability, "source": r.source,
        "reason": r.reason, "needs_root": r.needs_root, "status": r.status,
        "installed_version": r.installed_version, "log": r.log[:8000],
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "decided_at": r.decided_at,
    }


async def _get_install_or_404(req_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession) -> InstallRequest:
    req = await session.get(InstallRequest, req_id)
    if req is None or req.user_id != user_id:
        raise HTTPException(status_code=404, detail="install_request_not_found")
    return req
