"""WEBSITE collector tests over real local HTTP: article + index modes, dedup,
versioning, same_event_candidate, cancellation, malformed HTML, content types."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.collection import ContentRelation, RawArchive, Source
from app.modules.collection.runner import run_collection_for_source
from app.modules.collection.storage import reset_store
from app.modules.collection.web import WebsiteCollector
from tests._feedserver import FeedServer

pytestmark = pytest.mark.asyncio(loop_scope="session")


def article_html(title: str, body: str, canonical: str, author: str = "محرر") -> str:
    return f"""<!doctype html><html lang="ar"><head>
<meta property="og:title" content="{title}">
<meta name="author" content="{author}">
<meta property="article:published_time" content="2026-08-29T10:00:00Z">
<link rel="canonical" href="{canonical}">
</head><body><article><h1>{title}</h1><p>{body}</p></article></body></html>"""


@pytest.fixture
def server():
    s = FeedServer().start()
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def collector_env(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "collector_allow_private_hosts", True)
    monkeypatch.setattr(s, "collector_min_host_interval_seconds", 0.0)
    monkeypatch.setattr(s, "collector_respect_robots", False)
    monkeypatch.setattr(s, "collector_max_retries", 1)
    monkeypatch.setattr(s, "raw_store_backend", "filesystem")
    monkeypatch.setattr(s, "raw_store_fs_path", str(tmp_path / "arc"))
    reset_store()
    yield
    reset_store()


async def _mk(db, url, config=None, name="Web"):
    src = Source(name=name, source_type="WEBSITE", url=url, language="ar",
                 category="security", reliability="C", collection_interval_seconds=60,
                 extraction_config=config)
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return src


async def _rows(db, sid):
    return list((await db.execute(select(RawArchive).where(RawArchive.source_id == sid))).scalars())


async def test_article_mode_extracts_and_archives(server, db_session):
    server.set("/story", article_html("عنوان الخبر", "متن الخبر الكافي للطول والتحليل الحقيقي", "http://x/story"), "text/html")
    src = await _mk(db_session, f"{server.url}/story")
    run = await run_collection_for_source(db_session, src)
    assert run.status == "success" and run.items_new == 1 and run.items_discovered == 1
    rows = await _rows(db_session, src.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.author == "محرر"
    assert row.extracted and "متن الخبر" in row.extracted["body"]
    assert row.content_type == "text/html"
    assert row.title == "عنوان الخبر"


async def test_index_mode_discovers_and_archives(server, db_session):
    server.set("/a1", article_html("خبر ١", "متن المقال الأول الطويل بما يكفي", "http://x/a1"), "text/html")
    server.set("/a2", article_html("خبر ٢", "متن المقال الثاني الطويل بما يكفي", "http://x/a2"), "text/html")
    index = f'<html><body><main><h2><a href="{server.url}/a1">١</a></h2><h2><a href="{server.url}/a2">٢</a></h2></main></body></html>'
    server.set("/index", index, "text/html")
    src = await _mk(db_session, f"{server.url}/index", config={"mode": "index", "max_articles": 10})
    run = await run_collection_for_source(db_session, src)
    assert run.items_discovered == 2 and run.items_new == 2
    assert len(await _rows(db_session, src.id)) == 2


async def test_website_versioning(server, db_session):
    server.set("/s", article_html("عنوان", "المتن الأصلي للمقال", "http://x/s"), "text/html")
    src = await _mk(db_session, f"{server.url}/s")
    await run_collection_for_source(db_session, src)
    server.set("/s", article_html("عنوان", "المتن بعد تحديث جوهري حقيقي", "http://x/s"), "text/html")
    run2 = await run_collection_for_source(db_session, src)
    assert run2.items_versioned == 1
    rows = await _rows(db_session, src.id)
    assert {r.version for r in rows} == {1, 2}


async def test_same_event_candidate_across_sources(server, db_session):
    # Syndicated/wire copy: identical article text, different source + URL.
    shared_title = "خبر مشترك عن الحدث نفسه"
    shared_body = "نص خبر متطابق تماماً يُنشر من مصدرين مختلفين حول الحدث نفسه بتفاصيل كافية"
    server.set("/src-a", article_html(shared_title, shared_body, "http://a/x"), "text/html")
    server.set("/src-b", article_html(shared_title, shared_body, "http://b/x"), "text/html")
    a = await _mk(db_session, f"{server.url}/src-a", name="A")
    b = await _mk(db_session, f"{server.url}/src-b", name="B")
    await run_collection_for_source(db_session, a)
    await run_collection_for_source(db_session, b)

    rels = (await db_session.execute(
        select(func.count()).select_from(ContentRelation)
        .where(ContentRelation.relation_type == "same_event_candidate")
    )).scalar_one()
    assert rels >= 1
    # Both items still exist (nothing deleted/merged).
    assert len(await _rows(db_session, a.id)) == 1
    assert len(await _rows(db_session, b.id)) == 1


async def test_cancellation_stops_index(server, db_session):
    # Collector-level cancellation: stop after the first article.
    for i in range(5):
        server.set(f"/c{i}", article_html(f"خبر {i}", f"متن المقال {i} الطويل كفاية", f"http://x/c{i}"), "text/html")
    links = "".join(f'<h2><a href="{server.url}/c{i}">x</a></h2>' for i in range(5))
    server.set("/idx", f"<html><body><main>{links}</main></body></html>", "text/html")
    src = await _mk(db_session, f"{server.url}/idx", config={"mode": "index", "max_articles": 10})

    calls = {"n": 0}

    def cancel_after_one():
        calls["n"] += 1
        return calls["n"] > 1

    result = await WebsiteCollector().collect(src, should_cancel=cancel_after_one)
    assert result.cancelled is True
    assert len(result.items) < result.discovered


async def test_malformed_html_still_archives(server, db_session):
    server.set("/m", "<html><head><title>ناقص<body><p>فقرة بلا إغلاق للمقال", "text/html")
    src = await _mk(db_session, f"{server.url}/m")
    run = await run_collection_for_source(db_session, src)
    assert run.status == "success"  # best-effort extraction, no crash


async def test_unsupported_content_type_fails(server, db_session):
    server.set("/pdf", b"%PDF-1.5 not really html", "application/pdf")
    src = await _mk(db_session, f"{server.url}/pdf")
    run = await run_collection_for_source(db_session, src)
    assert run.status == "failure"
    assert "content-type" in (src.last_error or "").lower()
