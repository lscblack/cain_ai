"""Per-operator workspace — where KAI writes files and runs the shell.

Every operator gets an isolated directory under ``settings.kai_workspace_dir``.
Files KAI creates there (via ``file.write`` or as a side effect of a shell
command) are registered as :class:`~app.database.models.security.KaiFile` rows so
they appear as downloadable assets in the chat. Downloads are validated to stay
inside the operator's own workspace (no path traversal).
"""
from __future__ import annotations

import mimetypes
import os
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.models.security import KaiFile

WRITE_OP_KEY = "file.write"
LIST_OP_KEY = "file.list"

_MAX_WRITE_BYTES = 25 * 1024 * 1024  # 25 MiB per file.write


def _root() -> Path:
    root = Path(os.path.expanduser(get_settings().kai_workspace_dir)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def operator_dir(user_id: uuid.UUID) -> Path:
    """The operator's workspace directory (created on demand)."""
    d = _root() / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_cwd(user_id: uuid.UUID, conversation_id: uuid.UUID | None) -> str:
    """Initial working directory for a shell session. One dir per operator so
    cwd/state persists across a conversation's commands."""
    return str(operator_dir(user_id))


def _safe_relname(filename: str) -> str:
    """Reduce a requested filename to a safe relative path under the workspace."""
    name = (filename or "").strip().replace("\\", "/")
    # Drop any leading slashes / drive, collapse .. segments.
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    cleaned = "/".join(parts) or "file"
    # Guard each segment against anything exotic.
    cleaned = re.sub(r"[^A-Za-z0-9._/\- ]", "_", cleaned)
    return cleaned[:300]


def _content_type(path: Path) -> str:
    ctype, _ = mimetypes.guess_type(str(path))
    return ctype or "application/octet-stream"


def file_out(row: KaiFile) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "rel_path": row.rel_path,
        "size": row.size,
        "content_type": row.content_type,
        "conversation_id": str(row.conversation_id) if row.conversation_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "download_url": f"/chat/files/{row.id}/download",
    }


async def _existing_by_relpath(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, KaiFile]:
    rows = (
        await session.execute(select(KaiFile).where(KaiFile.user_id == user_id))
    ).scalars().all()
    return {r.rel_path: r for r in rows}


async def _register(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    path: Path,
    rel_path: str,
    existing: dict[str, KaiFile] | None = None,
) -> KaiFile:
    """Upsert a KaiFile row for a file on disk (by rel_path)."""
    existing = existing if existing is not None else await _existing_by_relpath(session, user_id)
    size = path.stat().st_size if path.exists() else 0
    row = existing.get(rel_path)
    if row is None:
        row = KaiFile(
            user_id=user_id,
            conversation_id=conversation_id,
            name=path.name,
            rel_path=rel_path,
            size=size,
            content_type=_content_type(path),
        )
        session.add(row)
    else:
        row.size = size
        if conversation_id is not None and row.conversation_id is None:
            row.conversation_id = conversation_id
        session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def write_file(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    filename: str,
    content: str,
) -> dict:
    """Write a UTF-8 text file into the operator's workspace and register it."""
    rel = _safe_relname(filename)
    if not rel:
        return {"ok": False, "status": "error", "error": "filename required",
                "operation": WRITE_OP_KEY, "tool": "files"}
    data = (content or "").encode("utf-8")
    if len(data) > _MAX_WRITE_BYTES:
        return {"ok": False, "status": "error", "operation": WRITE_OP_KEY, "tool": "files",
                "error": f"content too large ({len(data)} bytes, max {_MAX_WRITE_BYTES})"}

    base = operator_dir(user_id)
    path = (base / rel).resolve()
    # Defence in depth: never escape the operator's workspace.
    if base not in path.parents and path != base:
        return {"ok": False, "status": "error", "operation": WRITE_OP_KEY, "tool": "files",
                "error": "invalid path"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    row = await _register(
        session, user_id=user_id, conversation_id=conversation_id, path=path, rel_path=rel,
    )
    return {
        "ok": True, "status": "ok", "operation": WRITE_OP_KEY, "tool": "files",
        "posture": "file", "file": file_out(row), "files": [file_out(row)],
        "message": f"Wrote {row.name} ({row.size} bytes) — ready to download.",
    }


async def list_files(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None = None,
) -> dict:
    """List the operator's workspace files, first syncing any new files on disk
    (e.g. created by a shell command) into KaiFile rows so they are downloadable."""
    base = operator_dir(user_id)
    existing = await _existing_by_relpath(session, user_id)

    # Sync disk → DB: register any regular file not yet tracked.
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = str(p.relative_to(base))
        except ValueError:
            continue
        if rel not in existing:
            await _register(
                session, user_id=user_id, conversation_id=conversation_id,
                path=p, rel_path=rel, existing=existing,
            )

    rows = (
        await session.execute(
            select(KaiFile).where(KaiFile.user_id == user_id).order_by(KaiFile.created_at.desc())
        )
    ).scalars().all()
    files = [file_out(r) for r in rows if (base / r.rel_path).exists()]
    return {"ok": True, "status": "ok", "operation": LIST_OP_KEY, "tool": "files",
            "posture": "file", "files": files, "count": len(files)}


async def resolve_download(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    file_id: uuid.UUID,
) -> tuple[Path, KaiFile] | None:
    """Resolve a KaiFile to its on-disk path, validating ownership + containment.
    Returns ``(path, row)`` or ``None`` if not found / out of bounds / missing."""
    row = await session.get(KaiFile, file_id)
    if row is None or row.user_id != user_id:
        return None
    base = operator_dir(user_id)
    path = (base / row.rel_path).resolve()
    if (base not in path.parents and path != base) or not path.is_file():
        return None
    return path, row
