"""ChatRun approval-gate plumbing, in isolation from HTTP."""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app import chat_runs


@pytest.fixture
def run():
    r = chat_runs.start_run(uuid.uuid4(), uuid.uuid4())
    assert r is not None
    return r


async def test_approve_resolves_the_waiter(run):
    fut = run.request_approval({"operation": "x"})
    assert run.pending_approval == {"operation": "x"}
    assert run.decide(True) is True
    assert await fut is True
    assert run.pending_approval is None  # cleared once decided


async def test_decline_resolves_false(run):
    fut = run.request_approval({"operation": "x"})
    assert run.decide(False) is True
    assert await fut is False


async def test_deciding_twice_the_second_is_a_no_op(run):
    run.request_approval({"operation": "x"})
    assert run.decide(True) is True
    assert run.decide(True) is False  # already decided


async def test_deciding_with_nothing_pending_is_a_no_op(run):
    assert run.decide(True) is False


async def test_finish_resolves_any_orphaned_waiter(run):
    """A turn that ends (cancelled, crashed) while awaiting approval must not
    leave the waiter hanging forever."""
    fut = run.request_approval({"operation": "x"})
    await run.finish()
    assert await asyncio.wait_for(fut, timeout=1) is False
