"""Celery tasks. Tasks are sync entry points that drive the async runner.

The heavy lifting lives in `runner` (shared with the API's manual trigger), so
the worker and the API always collect through identical, tested logic.
"""
from __future__ import annotations

import asyncio
import uuid

from app.core.logging import get_logger
from app.db.session import dispose_engine, get_sessionmaker
from app.worker.celery_app import celery

log = get_logger("worker")


async def _collect_due() -> int:
    from app.modules.collection.runner import run_due_sources

    async with get_sessionmaker()() as db:
        ran = await run_due_sources(db)
    await dispose_engine()
    return len(ran)


async def _collect_one(source_id: uuid.UUID) -> str:
    from app.modules.collection.runner import run_collection_for_source
    from app.modules.collection.service import get_source

    async with get_sessionmaker()() as db:
        source = await get_source(db, source_id)
        run = await run_collection_for_source(db, source)
        status = run.status
    await dispose_engine()
    return status


@celery.task(name="app.worker.tasks.collect_due_sources")
def collect_due_sources() -> int:
    count = asyncio.run(_collect_due())
    log.info("beat_collected", sources=count)
    return count


@celery.task(name="app.worker.tasks.collect_source")
def collect_source(source_id: str) -> str:
    return asyncio.run(_collect_one(uuid.UUID(source_id)))
