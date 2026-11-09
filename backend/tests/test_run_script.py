"""run_workspace_script: validation + execution through the shared shell executor."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.core.security import hash_password
from app.database.models.user import User
from app.security import capabilities as caps_mod
from app.security import service
from app.security import workspace as ws


@pytest_asyncio.fixture
async def uid(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "kai_workspace_dir", str(tmp_path / "ws"))
    user = User(email="script@example.com", password_hash=hash_password("not-used-here-123"))
    db_session.add(user)
    await db_session.flush()
    await caps_mod.update_capabilities(db_session, user.id, shell_enabled=True, shell_sudo=False)
    return user.id


def _write(uid, name, body):
    p = ws.operator_dir(uid) / name
    p.write_text(body)
    return p


async def test_run_workspace_script_executes_and_returns_stdout(db_session, uid):
    _write(uid, "hello.sh", "echo KAI_RAN_OK\n")
    out = await service.run_workspace_script(
        db_session, user_id=uid, conversation_id=None, filename="hello.sh", sudo=False)
    assert out["ok"] and "KAI_RAN_OK" in out["stdout"]


async def test_run_workspace_script_rejects_traversal(db_session, uid):
    for bad in ["../../etc/passwd", "/etc/passwd", "../x.sh"]:
        out = await service.run_workspace_script(
            db_session, user_id=uid, conversation_id=None, filename=bad)
        assert out["status"] == "error" and out["reason"] == "bad_script"


async def test_run_workspace_script_requires_sh_extension(db_session, uid):
    _write(uid, "note.txt", "echo hi\n")
    out = await service.run_workspace_script(
        db_session, user_id=uid, conversation_id=None, filename="note.txt")
    assert out["reason"] == "bad_script"


async def test_run_workspace_script_sudo_blocked_when_disabled(db_session, uid):
    _write(uid, "hello.sh", "echo hi\n")
    out = await service.run_workspace_script(
        db_session, user_id=uid, conversation_id=None, filename="hello.sh", sudo=True)
    assert out["status"] == "blocked" and out["reason"] == "sudo_disabled"


async def test_run_workspace_script_name_with_space(db_session, uid):
    _write(uid, "a b.sh", "echo SPACE_OK\n")
    out = await service.run_workspace_script(
        db_session, user_id=uid, conversation_id=None, filename="a b.sh")
    assert out["ok"], out
    assert "SPACE_OK" in out["stdout"]


async def test_run_workspace_script_ignores_session_cwd(db_session, uid):
    from app.security import terminal

    _write(uid, "hello.sh", "echo REAL_WORKSPACE\n")
    sub = ws.operator_dir(uid) / "sub"
    sub.mkdir()
    (sub / "hello.sh").write_text("echo DECOY\n")
    key = f"u:{uid}"
    try:
        await terminal.exec_in_session(key, "cd sub", cwd=str(ws.operator_dir(uid)), interactive=False)
        out = await service.run_workspace_script(
            db_session, user_id=uid, conversation_id=None, filename="hello.sh")
    finally:
        terminal.close_session(key)
    assert "REAL_WORKSPACE" in out["stdout"] and "DECOY" not in out["stdout"]
