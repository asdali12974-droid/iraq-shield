"""Collection engine tests.

A real local HTTP server serves genuine RSS bytes; the collector performs an
actual fetch + parse + archive. NOTHING is inserted into the DB directly — data
enters only through the real collection path. (This is a local HTTP harness for
the collector, NOT a stand-in for the public internet, which is blocked here.)
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select, text

from app.core.config import get_settings
from app.models.collection import RawArchive, Source
from app.modules.collection.runner import run_collection_for_source
from app.modules.collection.storage import get_store, reset_store
from tests._feedserver import FeedServer, make_rss

pytestmark = pytest.mark.asyncio(loop_scope="session")

ITEMS_V1 = [
    {"guid": "iq-001", "title": "خبر أمني ١", "link": "http://ex/1", "description": "تفاصيل الحدث الأول"},
    {"guid": "iq-002", "title": "خبر أمني ٢", "link": "http://ex/2", "description": "تفاصيل الحدث الثاني"},
]


@pytest.fixture
def feed_server():
    srv = FeedServer().start()
    yield srv
    srv.stop()


@pytest.fixture(autouse=True)
def collector_settings(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "collector_allow_private_hosts", True)
    monkeypatch.setattr(s, "collector_min_host_interval_seconds", 0.0)
    monkeypatch.setattr(s, "collector_respect_robots", True)
    monkeypatch.setattr(s, "collector_max_retries", 3)
    monkeypatch.setattr(s, "collector_backoff_base_seconds", 0.0)
    monkeypatch.setattr(s, "collector_timeout_seconds", 5.0)
    monkeypatch.setattr(s, "raw_store_backend", "filesystem")
    monkeypatch.setattr(s, "raw_store_fs_path", str(tmp_path / "archive"))
    reset_store()
    yield
    reset_store()


async def _mk_source(db, url: str, name: str = "Test RSS") -> Source:
    src = Source(
        name=name, source_type="RSS", url=url, language="ar",
        category="security", reliability="C", enabled=True,
        collection_interval_seconds=60,
    )
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return src


async def _archive_rows(db, source_id):
    res = await db.execute(
        select(RawArchive).where(RawArchive.source_id == source_id).order_by(RawArchive.version)
    )
    return list(res.scalars().all())


# --------------------------------------------------------------------------- #
async def test_collect_archives_and_health(feed_server, db_session):
    feed_server.set("/feed.xml", make_rss(ITEMS_V1))
    src = await _mk_source(db_session, f"{feed_server.url}/feed.xml")

    run = await run_collection_for_source(db_session, src)
    assert run.status == "success"
    assert run.items_seen == 2 and run.items_new == 2 and run.items_duplicate == 0

    rows = await _archive_rows(db_session, src.id)
    assert len(rows) == 2
    for row in rows:
        assert row.is_current and row.version == 1
        # Archive persistence: raw bytes really landed in the store and match hash.
        blob = get_store().get(row.raw_ref)
        assert blob and json.loads(blob)["id"] in ("iq-001", "iq-002")

    await db_session.refresh(src)
    assert src.total_runs == 1 and src.success_count == 1
    assert src.consecutive_failures == 0 and src.last_status == "success"
    assert src.health == "healthy"


async def test_dedup_on_rerun(feed_server, db_session):
    feed_server.set("/feed.xml", make_rss(ITEMS_V1))
    src = await _mk_source(db_session, f"{feed_server.url}/feed.xml")

    await run_collection_for_source(db_session, src)
    run2 = await run_collection_for_source(db_session, src)

    assert run2.items_seen == 2
    assert run2.items_new == 0 and run2.items_duplicate == 2 and run2.items_versioned == 0
    assert len(await _archive_rows(db_session, src.id)) == 2  # no new rows


async def test_versioning_on_real_change(feed_server, db_session):
    feed_server.set("/feed.xml", make_rss(ITEMS_V1))
    src = await _mk_source(db_session, f"{feed_server.url}/feed.xml")
    await run_collection_for_source(db_session, src)

    # Genuinely change one item's content -> new version; other stays a duplicate.
    changed = [dict(ITEMS_V1[0]), {**ITEMS_V1[1], "description": "تحديث جوهري للحدث الثاني"}]
    feed_server.set("/feed.xml", make_rss(changed))
    run2 = await run_collection_for_source(db_session, src)

    assert run2.items_versioned == 1 and run2.items_duplicate == 1 and run2.items_new == 0

    rows = await _archive_rows(db_session, src.id)
    assert len(rows) == 3  # 2 original + 1 new version
    versions_002 = [r for r in rows if r.external_id == "iq-002"]
    assert {r.version for r in versions_002} == {1, 2}
    assert [r.is_current for r in sorted(versions_002, key=lambda r: r.version)] == [False, True]
    v2 = next(r for r in versions_002 if r.version == 2)
    assert v2.supersedes_id == next(r.id for r in versions_002 if r.version == 1)


async def test_collection_failure_marks_health(feed_server, db_session):
    feed_server.set("/feed.xml", b"boom", content_type="text/plain", status=500)
    src = await _mk_source(db_session, f"{feed_server.url}/feed.xml")

    run = await run_collection_for_source(db_session, src)
    assert run.status == "failure"
    await db_session.refresh(src)
    assert src.failure_count == 1 and src.consecutive_failures == 1
    assert src.last_status == "failure" and src.health == "degraded"


async def test_robots_disallow_blocks(feed_server, db_session):
    feed_server.set("/robots.txt", "User-agent: *\nDisallow: /", content_type="text/plain")
    feed_server.set("/feed.xml", make_rss(ITEMS_V1))
    src = await _mk_source(db_session, f"{feed_server.url}/feed.xml")

    run = await run_collection_for_source(db_session, src)
    assert run.status == "failure"
    await db_session.refresh(src)
    assert "robots" in (src.last_error or "").lower()
    assert len(await _archive_rows(db_session, src.id)) == 0


async def test_timeout_marks_failure(feed_server, db_session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "collector_timeout_seconds", 0.5)
    monkeypatch.setattr(s, "collector_max_retries", 1)
    feed_server.set("/feed.xml", make_rss(ITEMS_V1), delay=1.5)  # stalls beyond timeout
    src = await _mk_source(db_session, f"{feed_server.url}/feed.xml")

    run = await run_collection_for_source(db_session, src)
    assert run.status == "failure"


async def test_retry_then_success(feed_server, db_session):
    # Fail twice with 503, then succeed — retries/backoff must recover.
    feed_server.set("/feed.xml", make_rss(ITEMS_V1), fail_times=2)
    src = await _mk_source(db_session, f"{feed_server.url}/feed.xml")

    run = await run_collection_for_source(db_session, src)
    assert run.status == "success" and run.items_new == 2


async def test_ssrf_blocked_source(db_session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "collector_allow_private_hosts", False)  # enforce guard
    # Unique path each run (test DB persists); the metadata IP is what's blocked.
    url = f"http://169.254.169.254/latest/feed-{uuid.uuid4().hex}.xml"
    src = await _mk_source(db_session, url, name="evil")

    run = await run_collection_for_source(db_session, src)
    assert run.status == "failure"
    await db_session.refresh(src)
    assert (src.last_error or "").startswith("ssrf_blocked")
    assert len(await _archive_rows(db_session, src.id)) == 0


async def test_conditional_not_modified_is_success(feed_server, db_session):
    # A 304 Not Modified must be handled as a successful no-op (not a failed
    # "redirect without Location"): httpx flags 304 as is_redirect.
    feed_server.set("/feed.xml", b"", status=304)
    src = await _mk_source(db_session, f"{feed_server.url}/feed.xml")
    run = await run_collection_for_source(db_session, src)
    assert run.status == "success"
    assert run.http_status == 304 and run.items_seen == 0
    assert len(await _archive_rows(db_session, src.id)) == 0


async def test_archive_is_delete_protected(feed_server, db_session):
    feed_server.set("/feed.xml", make_rss(ITEMS_V1))
    src = await _mk_source(db_session, f"{feed_server.url}/feed.xml")
    await run_collection_for_source(db_session, src)

    with pytest.raises(Exception) as exc:
        await db_session.execute(
            text("DELETE FROM raw_archive WHERE source_id = :sid").bindparams(sid=src.id)
        )
        await db_session.commit()
    assert "delete-protected" in str(exc.value).lower()
    await db_session.rollback()
