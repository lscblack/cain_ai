import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.agents import ratelimit as rl
from app.agents.ratelimit import (
    BUSY,
    MAX_CONCURRENT,
    RATE_LIMITED,
    TOTAL_PER_MIN,
    WEB_PER_MIN,
    RateLimited,
    acquire_slot,
    check_investigation_rate,
    investigation_slot,
    web_budget_exhausted,
)
from app.database.models.audit import AuditLog


@pytest.fixture(autouse=True)
def _no_slots_leak():
    rl._active.clear()
    yield
    assert rl._active == {}, "a slot leaked"


async def seed_audit(db, uid, n, *, web=False, age=0.0, action="people.investigate",
                     web_only=False, agents=("db",)):
    when = datetime.now(timezone.utc) - timedelta(seconds=age)
    q = {"name": "x", "web_only": True} if web_only else {"nid": "1", "web": web}
    for _ in range(n):
        db.add(AuditLog(actor_id=uid, action=action, created_at=when,
                        detail={"query": q, "agents": list(agents)}))
    await db.commit()


def test_limits():
    assert (TOTAL_PER_MIN, WEB_PER_MIN, MAX_CONCURRENT) == (30, 5, 2)


async def test_total_budget_is_30_per_minute(db_session):
    uid = uuid.uuid4()
    await seed_audit(db_session, uid, TOTAL_PER_MIN - 1)
    assert await check_investigation_rate(db_session, uid, web=False) is None
    await seed_audit(db_session, uid, 1)
    assert await check_investigation_rate(db_session, uid, web=False) == RATE_LIMITED
    # other users and other actions are not counted
    assert await check_investigation_rate(db_session, uuid.uuid4(), web=True) is None
    uid2 = uuid.uuid4()
    await seed_audit(db_session, uid2, 40, action="people.lookup", agents=("db", "web"))
    assert await check_investigation_rate(db_session, uid2, web=True) is None


async def test_web_budget_counts_what_actually_ran(db_session):
    # auto-web runs (person not found) are audited with query.web=false
    uid = uuid.uuid4()
    await seed_audit(db_session, uid, 3, web=False, agents=("db", "web"))
    assert not await web_budget_exhausted(db_session, uid)
    await seed_audit(db_session, uid, 1, web=True, agents=("db",))
    await seed_audit(db_session, uid, 1, web_only=True, agents=("web",))
    assert await web_budget_exhausted(db_session, uid)
    assert await check_investigation_rate(db_session, uid, web=True) == RATE_LIMITED
    assert await check_investigation_rate(db_session, uid, web=False) is None


async def test_db_only_runs_do_not_use_web_budget(db_session):
    uid = uuid.uuid4()
    await seed_audit(db_session, uid, 10, web=False, agents=("db", "relations"))
    assert not await web_budget_exhausted(db_session, uid)


async def test_old_rows_do_not_count(db_session):
    uid = uuid.uuid4()
    await seed_audit(db_session, uid, 40, web=True, age=120, agents=("db", "web"))
    assert await check_investigation_rate(db_session, uid, web=True) is None
    assert not await web_budget_exhausted(db_session, uid)


async def test_concurrency_cap_and_release():
    uid = uuid.uuid4()
    a, b = acquire_slot(uid), acquire_slot(uid)
    with pytest.raises(RateLimited) as ei:
        acquire_slot(uid)
    assert str(ei.value) == BUSY
    assert rl._active[uid] == MAX_CONCURRENT  # the rejected attempt holds nothing
    acquire_slot(uuid.uuid4()).release()  # other users unaffected
    a.release()
    a.release()  # idempotent
    c = acquire_slot(uid)
    b.release()
    c.release()


async def test_slot_released_after_exception():
    uid = uuid.uuid4()
    with pytest.raises(RuntimeError):
        async with investigation_slot(uid):
            raise RuntimeError("boom")
    async with investigation_slot(uid):
        async with investigation_slot(uid):
            with pytest.raises(RateLimited):
                async with investigation_slot(uid):
                    pass


async def test_slot_released_on_cancel():
    uid = uuid.uuid4()

    async def hold():
        async with investigation_slot(uid):
            await asyncio.sleep(60)
    t = asyncio.ensure_future(hold())
    await asyncio.sleep(0.01)
    assert rl._active[uid] == 1
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    assert uid not in rl._active
