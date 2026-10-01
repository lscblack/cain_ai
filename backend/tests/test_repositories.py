from app.database.models.user import User
from app.database.repositories.audit_repo import AuditRepository
from app.database.repositories.user_repo import UserRepository


async def test_user_repo_count_and_get_by_email(db_session):
    repo = UserRepository(db_session)
    assert await repo.count() == 0

    await repo.add(User(email="op@example.com", password_hash="h"))
    await db_session.commit()

    assert await repo.count() == 1
    found = await repo.get_by_email("op@example.com")
    assert found is not None and found.email == "op@example.com"
    assert await repo.get_by_email("missing@example.com") is None


async def test_audit_repo_record(db_session):
    repo = AuditRepository(db_session)
    entry = await repo.record("operator.login", detail={"email": "op@example.com"}, ip="1.1.1.1")
    await db_session.commit()
    assert entry.id is not None
    assert await repo.count() == 1
