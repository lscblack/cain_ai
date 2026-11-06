"""Background runner for enrichment jobs.

Each job runs as a tracked asyncio task with its OWN database session (request
sessions can't outlive the request). Jobs are pausable/cancellable. Because the
flows are idempotent, a job interrupted by a restart can simply be re-run.
"""
from __future__ import annotations

import uuid

from app.core.logging import get_logger
from app.database.models.enrich import ScrapeJob
from app.enrich.scraper import JobControl, run_job

_log = get_logger("kai.enrich")

_CONTROLS: dict[str, JobControl] = {}
_TASKS: dict[str, "object"] = {}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def _runner(job_id: uuid.UUID, user_id: uuid.UUID, control: JobControl) -> None:
    import asyncio

    from app.database.session import async_session_maker

    key = str(job_id)
    try:
        async with async_session_maker() as session:
            job = await session.get(ScrapeJob, job_id)
            if job is None:
                return
            job.status = "running"
            job.started_at = _now_iso()
            job.last_message = "started"
            session.add(job)
            await session.commit()

            try:
                await run_job(session, job, control, user_id)
                job = await session.get(ScrapeJob, job_id)
                if control.cancelled:
                    job.status = "cancelled"
                    job.last_message = "cancelled by operator"
                else:
                    job.status = "done"
                    job.last_message = "completed"
            except asyncio.CancelledError:
                job = await session.get(ScrapeJob, job_id)
                if job is not None:
                    job.status = "cancelled"
                    job.last_message = "cancelled"
                raise
            except Exception as exc:  # noqa: BLE001
                _log.exception("enrichment job failed")
                job = await session.get(ScrapeJob, job_id)
                if job is not None:
                    job.status = "error"
                    job.last_message = f"error: {exc}"[:500]
            finally:
                if job is not None:
                    job.finished_at = _now_iso()
                    session.add(job)
                    await session.commit()
    finally:
        _CONTROLS.pop(key, None)
        _TASKS.pop(key, None)


async def start_job(job_id: uuid.UUID, user_id: uuid.UUID) -> None:
    import asyncio

    key = str(job_id)
    if key in _TASKS:
        return  # already running
    control = JobControl()
    _CONTROLS[key] = control
    _TASKS[key] = asyncio.create_task(_runner(job_id, user_id, control))


def is_running(job_id: uuid.UUID) -> bool:
    return str(job_id) in _TASKS


def pause_job(job_id: uuid.UUID) -> bool:
    c = _CONTROLS.get(str(job_id))
    if c is None:
        return False
    c.pause()
    return True


def resume_job(job_id: uuid.UUID) -> bool:
    c = _CONTROLS.get(str(job_id))
    if c is None:
        return False
    c.resume()
    return True


def cancel_job(job_id: uuid.UUID) -> bool:
    c = _CONTROLS.get(str(job_id))
    if c is None:
        return False
    c.cancel()
    c.resume()  # unblock a paused gate so it can observe the cancel
    return True


async def reset_stale_jobs() -> None:
    """On startup, mark jobs left 'running' by a killed process as interrupted."""
    from sqlalchemy import update

    from app.database.session import async_session_maker

    try:
        async with async_session_maker() as session:
            await session.execute(
                update(ScrapeJob)
                .where(ScrapeJob.status.in_(("running", "queued")))
                .values(status="error", last_message="interrupted by server restart",
                        finished_at=_now_iso())
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        _log.exception("failed to reset stale enrichment jobs")
