import uuid
from datetime import datetime, timedelta, timezone

from app.agents.ratelimit import MAX_PER_MINUTE, MAX_WEB_PER_MINUTE, check_investigation_rate
from app.database.models.audit import AuditLog


async def seed_audit(db, uid, n, *, web=False, age=0.0, action="people.investigate", web_only=False):
    when = datetime.now(timezone.utc) - timedelta(seconds=age)
    q = {"name": "x", "web_only": True} if web_only else {"nid": "1", "web": web}
    for _ in range(n):
        db.add(AuditLog(actor_id=uid, action=action, detail={"query": q}, created_at=when))
    await db.commit()


def test_limits():
    assert MAX_PER_MINUTE == 10 and MAX_WEB_PER_MINUTE == 5


async def test_under_limit_is_allowed(db_session):
    uid = uuid.uuid4()
    await seed_audit(db_session, uid, MAX_PER_MINUTE - 1)
    assert await check_investigation_rate(db_session, uid, web=False) is None


async def test_total_limit(db_session):
    uid = uuid.uuid4()
    await seed_audit(db_session, uid, MAX_PER_MINUTE)
    msg = await check_investigation_rate(db_session, uid, web=False)
    assert msg == "rate limited: too many investigations, retry in a minute"
    # other users and other actions are not counted
    assert await check_investigation_rate(db_session, uuid.uuid4(), web=True) is None
    uid2 = uuid.uuid4()
    await seed_audit(db_session, uid2, 20, action="people.lookup")
    assert await check_investigation_rate(db_session, uid2, web=True) is None


async def test_web_limit_only_applies_to_web_requests(db_session):
    uid = uuid.uuid4()
    await seed_audit(db_session, uid, 3, web=True)
    await seed_audit(db_session, uid, 2, web_only=True)  # web-only cards look up the web too
    assert await check_investigation_rate(db_session, uid, web=True) is not None
    assert await check_investigation_rate(db_session, uid, web=False) is None


async def test_old_rows_do_not_count(db_session):
    uid = uuid.uuid4()
    await seed_audit(db_session, uid, 30, web=True, age=120)
    assert await check_investigation_rate(db_session, uid, web=True) is None
