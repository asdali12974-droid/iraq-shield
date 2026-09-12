"""Scheduler/worker logic: run_due_sources honors each source's interval, and
the Celery app/tasks are wired correctly (without needing a running broker)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from app.core.config import get_settings
from app.models.collection import Source
from app.modules.collection.runner import run_due_sources
from app.modules.collection.storage import reset_store
from tests._feedserver import FeedServer, make_rss

pytestmark = pytest.mark.asyncio(loop_scope="session")

ITEMS = [{"guid": "s-1", "title": "ت", "link": "http://ex/1", "description": "و"}]


@pytest.fixture
def feed_server():
    srv = FeedServer().start()
    srv.set("/feed.xml", make_rss(ITEMS))
    yield srv
    srv.stop()


@pytest.fixture(autouse=True)
def collector_env(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "collector_allow_private_hosts", True)
    monkeypatch.setattr(s, "collector_min_host_interval_seconds", 0.0)
    monkeypatch.setattr(s, "collector_respect_robots", False)
    monkeypatch.setattr(s, "raw_store_backend", "filesystem")
    monkeypatch.setattr(s, "raw_store_fs_path", str(tmp_path / "a"))
    reset_store()
    yield
    reset_store()


async def test_run_due_sources_respects_interval(feed_server, db_session):
    # Isolate from any sources created by other tests.
    await db_session.execute(update(Source).values(enabled=False))
    await db_session.commit()

    due = Source(name="due", source_type="RSS", url=f"{feed_server.url}/feed.xml",
                 enabled=True, collection_interval_seconds=60)
    not_due = Source(name="not_due", source_type="RSS", url=f"{feed_server.url}/other.xml",
                     enabled=True, collection_interval_seconds=3600,
                     last_success_at=datetime.now(tz=UTC))
    db_session.add_all([due, not_due])
    await db_session.commit()

    ran = await run_due_sources(db_session)
    assert due.id in ran and not_due.id not in ran

    await db_session.refresh(due)
    await db_session.refresh(not_due)
    assert due.total_runs == 1
    assert not_due.total_runs == 0  # interval not elapsed -> skipped


def test_celery_app_and_tasks_registered():
    import app.worker.tasks  # noqa: F401  (registers the tasks on the app)
    from app.worker.celery_app import celery

    assert celery.main == "iraqshield"
    assert "app.worker.tasks.collect_due_sources" in celery.tasks
    assert "app.worker.tasks.collect_source" in celery.tasks
    # Beat schedule dispatches the due-scan.
    assert "collect-due-sources" in celery.conf.beat_schedule
