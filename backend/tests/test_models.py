import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.database.models import AuditLog, User


async def test_create_and_read_user(db_session):
    user = User(email="op@example.com", password_hash="x")
    db_session.add(user)
    await db_session.commit()

    result = await db_session.execute(select(User).where(User.email == "op@example.com"))
    fetched = result.scalar_one()
    assert fetched.id is not None
    assert fetched.created_at is not None


async def test_user_email_unique(db_session):
    db_session.add(User(email="dup@example.com", password_hash="a"))
    await db_session.commit()
    db_session.add(User(email="dup@example.com", password_hash="b"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_create_audit_log(db_session):
    log = AuditLog(action="operator.login", actor_id=uuid.uuid4(), detail={"ok": True}, ip="1.2.3.4")
    db_session.add(log)
    await db_session.commit()
    result = await db_session.execute(select(AuditLog))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].detail == {"ok": True}
