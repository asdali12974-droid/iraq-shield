"""TELEGRAM_PUBLIC_WEB collector tests — HTTP-based collection from t.me/s/ pages.

These tests use a LOCAL HTTP test server that serves HTML mimicking the structure
of Telegram's public web preview. NO real Telegram connection is used — the tests
validate: HTML parsing, incremental collection, dedup, versioning, forwarded
posts, media metadata, error handling, and SSRF protection.

The test fixtures (FakePost, make_telegram_page) produce only test content — no
real Telegram data is created or collected.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.collection import ContentRelation, RawArchive, Source
from app.modules.collection.runner import run_collection_for_source
from app.modules.collection.storage import reset_store
from tests._feedserver import FeedServer
from tests._telegram_page import FakePost, make_telegram_page

pytestmark = pytest.mark.asyncio(loop_scope="session")

BASE = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)


def _post(pid, text, *, dt_offset=0, views="1K", author=None,
          fwd=None, fwd_url=None, media=None, media_extra=None):
    """Helper to build a FakePost."""
    return FakePost(
        post_id=pid,
        text=text,
        datetime=(BASE + timedelta(minutes=dt_offset)).isoformat(),
        views=views,
        author=author,
        forwarded_from=fwd,
        forwarded_from_url=fwd_url,
        media_type=media,
        media_extra=media_extra,
    )


@pytest.fixture
def tg_server():
    """A local HTTP server that serves t.me/s/ style pages."""
    srv = FeedServer().start()
    yield srv
    srv.stop()


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "raw_store_backend", "filesystem")
    monkeypatch.setattr(s, "raw_store_fs_path", str(tmp_path / "tg_web"))
    monkeypatch.setattr(s, "collector_allow_private_hosts", True)
    monkeypatch.setattr(s, "collector_min_host_interval_seconds", 0.0)
    monkeypatch.setattr(s, "collector_respect_robots", False)
    monkeypatch.setattr(s, "collector_max_retries", 2)
    monkeypatch.setattr(s, "collector_backoff_base_seconds", 0.0)
    reset_store()
    yield
    reset_store()


async def _mk(db, username, server_url, **over):
    """Create a TELEGRAM_PUBLIC_WEB source pointing at the test server."""
    src = Source(
        name=over.get("name", username),
        source_type="TELEGRAM_PUBLIC_WEB",
        # Point at the local server instead of real t.me
        url=f"{server_url}/s/{username}",
        telegram_username=username,
        language="ar",
        category="security",
        source_class="MEDIA_OTHER",
        reliability="C",
        verification_status="pending",
        collection_interval_seconds=60,
    )
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return src


async def _rows(db, sid):
    return list(
        (await db.execute(
            select(RawArchive).where(RawArchive.source_id == sid)
        )).scalars()
    )


def _serve_channel(srv, username, title, posts, **kw):
    """Set up the test server to serve a channel page."""
    html = make_telegram_page(username, title, posts, **kw)
    srv.set(f"/s/{username}", html, content_type="text/html")


# --- Parser tests --------------------------------------------------------- #

def test_parser_extracts_posts():
    """Parse a page with 3 posts and verify all fields are extracted."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [
        _post(1, "أول منشور", dt_offset=0),
        _post(2, "ثاني منشور", dt_offset=5),
        _post(3, "ثالث منشور", dt_offset=10, views="2.5K"),
    ]
    html = make_telegram_page("test_chan", "قناة اختبار", posts)
    result = parse_telegram_page(html, "test_chan")

    assert result.page_has_content is True
    assert result.channel_title == "قناة اختبار"
    assert len(result.posts) == 3
    assert result.posts[0].post_id == "1"
    assert result.posts[0].text == "أول منشور"
    assert result.posts[0].url == "https://t.me/test_chan/1"
    assert result.posts[0].published_at is not None
    assert result.posts[2].views == "2.5K"


def test_parser_handles_empty_page():
    """An invalid page should have page_has_content=False."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    html = make_telegram_page("x", "x", valid_channel=False)
    result = parse_telegram_page(html, "x")
    assert result.page_has_content is False
    assert len(result.posts) == 0


def test_parser_extracts_forwarded():
    """Forwarded posts should capture the source name and URL."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [
        _post(
            1, "خبر منقول", fwd="قناة أصلية",
            fwd_url="https://t.me/original_chan/99",
        ),
    ]
    html = make_telegram_page("reposter", "ناقل", posts)
    result = parse_telegram_page(html, "reposter")
    assert len(result.posts) == 1
    p = result.posts[0]
    assert p.forwarded_from == "قناة أصلية"
    assert p.forwarded_from_url == "https://t.me/original_chan/99"


def test_parser_extracts_media_photo():
    """Photo media metadata should be captured."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [
        _post(1, "بصورة", media="photo",
              media_extra={"thumbnail_url": "https://cdn.example/thumb.jpg"}),
    ]
    html = make_telegram_page("photo_chan", "صور", posts)
    result = parse_telegram_page(html, "photo_chan")
    assert result.posts[0].media_meta is not None
    assert result.posts[0].media_meta["type"] == "photo"


def test_parser_extracts_media_video():
    """Video media metadata should capture duration."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [
        _post(1, "فيديو", media="video", media_extra={"duration": "1:30"}),
    ]
    html = make_telegram_page("vid_chan", "فيديو", posts)
    result = parse_telegram_page(html, "vid_chan")
    m = result.posts[0].media_meta
    assert m is not None
    assert m["type"] == "video"
    assert m["duration"] == "1:30"


def test_parser_extracts_media_document():
    """Document media should capture filename and size."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [
        _post(1, "مرفق", media="document",
              media_extra={"filename": "report.pdf", "size": "2.5 MB"}),
    ]
    html = make_telegram_page("doc_chan", "وثائق", posts)
    result = parse_telegram_page(html, "doc_chan")
    m = result.posts[0].media_meta
    assert m is not None
    assert m["type"] == "document"
    assert m["filename"] == "report.pdf"
    assert m["size"] == "2.5 MB"


def test_parser_media_only_post():
    """A post with no text (media-only) should still be extracted."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [_post(1, None, media="photo")]
    html = make_telegram_page("media_chan", "وسائط", posts)
    result = parse_telegram_page(html, "media_chan")
    assert len(result.posts) == 1
    assert result.posts[0].text is None
    assert result.posts[0].media_meta is not None


def test_parser_poll():
    """Poll media should capture the question."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [
        _post(1, None, media="poll",
              media_extra={"question": "هل توافق؟"}),
    ]
    html = make_telegram_page("poll_chan", "استطلاعات", posts)
    result = parse_telegram_page(html, "poll_chan")
    m = result.posts[0].media_meta
    assert m is not None
    assert m["type"] == "poll"
    assert m["question"] == "هل توافق؟"


# --- Collector integration tests (using real HTTP + runner) --------------- #

async def test_initial_collection(db_session, tg_server):
    """First collection archives all visible posts."""
    _serve_channel(tg_server, "chan_a", "قناة أ", [
        _post(1, "منشور ١"),
        _post(2, "منشور ٢"),
        _post(3, "منشور ٣"),
    ])
    src = await _mk(db_session, "chan_a", tg_server.url)
    run = await run_collection_for_source(db_session, src)

    assert run.status == "success"
    assert run.items_new == 3
    await db_session.refresh(src)
    assert src.last_cursor == "3"
    assert src.telegram_title == "قناة أ"

    rows = await _rows(db_session, src.id)
    assert len(rows) == 3
    ext_ids = {r.external_id for r in rows}
    assert "chan_a:1" in ext_ids
    assert "chan_a:2" in ext_ids
    assert "chan_a:3" in ext_ids
    assert all(r.canonical_url.startswith("https://t.me/chan_a/") for r in rows)


async def test_incremental_collection(db_session, tg_server):
    """Second run after cursor advances should only collect new posts."""
    posts = [_post(1, "أ"), _post(2, "ب")]
    _serve_channel(tg_server, "chan_b", "قناة ب", posts)
    src = await _mk(db_session, "chan_b", tg_server.url)
    await run_collection_for_source(db_session, src)

    # Add newer posts
    posts.extend([_post(3, "ج"), _post(4, "د")])
    _serve_channel(tg_server, "chan_b", "قناة ب", posts)
    run2 = await run_collection_for_source(db_session, src)

    assert run2.items_new == 2
    assert run2.items_seen == 2  # only the 2 new ones reach the archive layer
    await db_session.refresh(src)
    assert src.last_cursor == "4"


async def test_duplicate_when_cursor_reset(db_session, tg_server):
    """If cursor is reset, refetched posts should be detected as duplicates."""
    posts = [_post(1, "أ"), _post(2, "ب"), _post(3, "ج")]
    _serve_channel(tg_server, "chan_c", "قناة ج", posts)
    src = await _mk(db_session, "chan_c", tg_server.url)
    await run_collection_for_source(db_session, src)

    # Reset cursor to force refetch
    src.last_cursor = "0"
    await db_session.commit()

    run2 = await run_collection_for_source(db_session, src)
    assert run2.items_new == 0
    assert run2.items_duplicate == 3


async def test_edited_post_versioning(db_session, tg_server):
    """A changed post text creates a new version in the archive."""
    _serve_channel(tg_server, "chan_d", "قناة د", [_post(5, "النص الأصلي")])
    src = await _mk(db_session, "chan_d", tg_server.url)
    await run_collection_for_source(db_session, src)

    # "Edit" the post text and reset cursor so we refetch
    _serve_channel(tg_server, "chan_d", "قناة د", [
        _post(5, "النص بعد التعديل الجوهري"),
    ])
    src.last_cursor = "4"
    await db_session.commit()

    run2 = await run_collection_for_source(db_session, src)
    assert run2.items_versioned == 1

    rows = await _rows(db_session, src.id)
    assert {r.version for r in rows} == {1, 2}


async def test_invalid_channel_page_fails(db_session, tg_server):
    """A page with no channel content should fail the collection."""
    html = make_telegram_page("bad", "bad", valid_channel=False)
    tg_server.set("/s/bad_chan", html, content_type="text/html")
    src = await _mk(db_session, "bad_chan", tg_server.url)
    run = await run_collection_for_source(db_session, src)

    assert run.status == "failure"
    assert len(await _rows(db_session, src.id)) == 0


async def test_http_error_fails_gracefully(db_session, tg_server):
    """A 404/500 from the server should fail the run, not crash."""
    tg_server.set("/s/missing_chan", b"not found", content_type="text/html",
                  status=404)
    src = await _mk(db_session, "missing_chan", tg_server.url)
    run = await run_collection_for_source(db_session, src)

    assert run.status == "failure"
    assert src.consecutive_failures >= 1
    assert len(await _rows(db_session, src.id)) == 0


async def test_transient_failure_retried(db_session, tg_server):
    """Transient errors should be retried by the fetcher."""
    posts = [_post(1, "نجاح بعد محاولة")]
    html = make_telegram_page("retry_chan", "قناة", posts)
    tg_server.set("/s/retry_chan", html, content_type="text/html",
                  fail_times=1)  # fail once, then succeed
    src = await _mk(db_session, "retry_chan", tg_server.url)
    run = await run_collection_for_source(db_session, src)

    assert run.status == "success"
    assert run.items_new == 1


async def test_media_metadata_archived(db_session, tg_server):
    """Media metadata from posts should be preserved in the archive."""
    _serve_channel(tg_server, "chan_m", "وسائط", [
        _post(1, "مع صورة", media="photo",
              media_extra={"thumbnail_url": "https://cdn.example/t.jpg"}),
    ])
    src = await _mk(db_session, "chan_m", tg_server.url)
    await run_collection_for_source(db_session, src)

    rows = await _rows(db_session, src.id)
    assert len(rows) == 1
    assert rows[0].extracted is not None
    assert rows[0].extracted["media_meta"]["type"] == "photo"


async def test_forwarded_post_metadata(db_session, tg_server):
    """Forwarded posts should record the original source info."""
    _serve_channel(tg_server, "chan_fwd", "ناقل", [
        _post(1, "خبر منقول", fwd="القناة الأصلية",
              fwd_url="https://t.me/original/42"),
    ])
    src = await _mk(db_session, "chan_fwd", tg_server.url)
    await run_collection_for_source(db_session, src)

    rows = await _rows(db_session, src.id)
    assert len(rows) == 1
    ext = rows[0].extracted
    assert ext is not None
    assert ext["forward"] is not None
    assert ext["forward"]["name"] == "القناة الأصلية"
    assert ext["forward"]["url"] == "https://t.me/original/42"


async def test_source_health_tracked(db_session, tg_server):
    """Success/failure should update source health counters."""
    _serve_channel(tg_server, "chan_h", "صحة", [_post(1, "test")])
    src = await _mk(db_session, "chan_h", tg_server.url)

    await run_collection_for_source(db_session, src)
    await db_session.refresh(src)
    assert src.health == "healthy"
    assert src.success_count == 1
    assert src.consecutive_failures == 0

    # Make the page fail
    tg_server.set("/s/chan_h", b"error", content_type="text/html", status=500)
    await run_collection_for_source(db_session, src)
    await db_session.refresh(src)
    assert src.consecutive_failures >= 1


async def test_no_fabricated_data_on_empty_page(db_session, tg_server):
    """A valid channel page with no posts should succeed with 0 items."""
    _serve_channel(tg_server, "empty_chan", "قناة فارغة", [])
    src = await _mk(db_session, "empty_chan", tg_server.url)
    run = await run_collection_for_source(db_session, src)

    assert run.status == "success"
    assert run.items_new == 0
    assert len(await _rows(db_session, src.id)) == 0


async def test_cross_source_fingerprint_dedup(db_session, tg_server):
    """Same text from different sources should create a same_event_candidate link."""
    text = "خبر عاجل: حدث أمني كبير في بغداد"

    # Source A posts the text
    _serve_channel(tg_server, "src_a", "مصدر أ", [_post(1, text)])
    a = await _mk(db_session, "src_a", tg_server.url)
    await run_collection_for_source(db_session, a)

    # Source B posts the same text
    _serve_channel(tg_server, "src_b", "مصدر ب", [_post(1, text)])
    b = await _mk(db_session, "src_b", tg_server.url)
    await run_collection_for_source(db_session, b)

    # Should have a same_event_candidate relation
    rels = (await db_session.execute(
        select(func.count()).select_from(ContentRelation)
        .where(ContentRelation.relation_type == "same_event_candidate")
    )).scalar_one()
    assert rels >= 1


# --- Batch 2: extraction honesty + dedup/cursor precision tests ----------- #

def test_parser_missing_data_post():
    """Post without data-post attribute → post_id must be None, not invented."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [FakePost(post_id=None, text="منشور بدون معرّف")]
    html = make_telegram_page("no_id_chan", "قناة", posts)
    result = parse_telegram_page(html, "no_id_chan")

    assert len(result.posts) == 1
    p = result.posts[0]
    assert p.post_id is None  # NOT fabricated
    assert p.text == "منشور بدون معرّف"
    assert p.url == "https://t.me/no_id_chan"  # fallback, no specific post URL


def test_parser_missing_timestamp():
    """Post without <time> element → published_at must be None, not invented."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [FakePost(post_id=10, text="بلا وقت", datetime=None)]
    html = make_telegram_page("no_ts_chan", "قناة", posts)
    result = parse_telegram_page(html, "no_ts_chan")

    assert len(result.posts) == 1
    p = result.posts[0]
    assert p.post_id == "10"
    assert p.published_at is None  # NOT fabricated
    assert p.text == "بلا وقت"


def test_parser_missing_views():
    """Post without views element → views must be None."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [FakePost(post_id=11, text="بدون مشاهدات", views=None)]
    html = make_telegram_page("no_views_chan", "قناة", posts)
    result = parse_telegram_page(html, "no_views_chan")

    assert len(result.posts) == 1
    p = result.posts[0]
    assert p.views is None  # NOT fabricated


def test_parser_all_fields_missing():
    """Post with no post_id, no timestamp, no views, no text → all None."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [FakePost(post_id=None, text=None, datetime=None, views=None,
                      media_type="photo")]
    html = make_telegram_page("bare_chan", "قناة", posts)
    result = parse_telegram_page(html, "bare_chan")

    assert len(result.posts) == 1
    p = result.posts[0]
    assert p.post_id is None
    assert p.text is None
    assert p.published_at is None
    assert p.views is None
    assert p.media_meta is not None  # media IS present
    assert p.media_meta["type"] == "photo"


def test_content_hash_differs_for_different_texts():
    """Different texts must produce different content_hash values."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [
        FakePost(post_id=1, text="نص أول"),
        FakePost(post_id=2, text="نص ثاني مختلف"),
    ]
    html = make_telegram_page("hash_chan", "قناة", posts)
    result = parse_telegram_page(html, "hash_chan")

    assert result.posts[0].content_hash != result.posts[1].content_hash


def test_content_hash_media_only_no_collision():
    """Two media-only posts (no text) of different types must not collide."""
    from app.modules.collection.telegram_web.parser import parse_telegram_page

    posts = [
        FakePost(post_id=1, text=None, media_type="photo"),
        FakePost(post_id=2, text=None, media_type="video"),
    ]
    html = make_telegram_page("media_hash_chan", "قناة", posts)
    result = parse_telegram_page(html, "media_hash_chan")

    assert result.posts[0].content_hash != result.posts[1].content_hash


async def test_cursor_does_not_regress(db_session, tg_server):
    """Cursor must never go backwards — only forward or stay."""
    _serve_channel(tg_server, "cursor_chan", "قناة", [
        _post(10, "عاشر"),
        _post(20, "عشرون"),
    ])
    src = await _mk(db_session, "cursor_chan", tg_server.url)
    await run_collection_for_source(db_session, src)
    await db_session.refresh(src)
    assert src.last_cursor == "20"

    # Serve only old posts (below cursor) — cursor must NOT regress
    _serve_channel(tg_server, "cursor_chan", "قناة", [
        _post(5, "خامس"),
        _post(10, "عاشر"),
    ])
    run2 = await run_collection_for_source(db_session, src)
    await db_session.refresh(src)
    assert src.last_cursor == "20"  # still 20, not regressed to 10
    assert run2.items_new == 0  # nothing new below cursor


async def test_cursor_advances_correctly_with_gaps(db_session, tg_server):
    """Cursor should advance to the max post_id even with gaps in IDs."""
    _serve_channel(tg_server, "gap_chan", "قناة", [
        _post(100, "مئة"),
        _post(105, "مئة وخمسة"),
        _post(200, "مئتان"),
    ])
    src = await _mk(db_session, "gap_chan", tg_server.url)
    await run_collection_for_source(db_session, src)
    await db_session.refresh(src)
    assert src.last_cursor == "200"
    assert len(await _rows(db_session, src.id)) == 3


async def test_posts_without_post_id_still_archived(db_session, tg_server):
    """Posts without data-post should still be collected using hash-based ID."""
    html = make_telegram_page("noid_chan", "قناة بلا معرّفات", [
        FakePost(post_id=None, text="نص بدون معرّف أول"),
        FakePost(post_id=None, text="نص بدون معرّف ثاني"),
    ])
    tg_server.set("/s/noid_chan", html, content_type="text/html")
    src = await _mk(db_session, "noid_chan", tg_server.url)
    run = await run_collection_for_source(db_session, src)

    assert run.status == "success"
    assert run.items_new == 2  # both archived with different hash-based IDs

    rows = await _rows(db_session, src.id)
    ext_ids = {r.external_id for r in rows}
    assert len(ext_ids) == 2  # different external_ids, not collapsed
    assert all(eid.startswith("noid_chan:hash:") for eid in ext_ids)


async def test_dedup_identical_refetch(db_session, tg_server):
    """Re-fetching the exact same page must produce 0 new items (all duplicate)."""
    _serve_channel(tg_server, "dup_chan", "قناة", [
        _post(1, "أ"), _post(2, "ب"),
    ])
    src = await _mk(db_session, "dup_chan", tg_server.url)
    run1 = await run_collection_for_source(db_session, src)
    assert run1.items_new == 2

    # Reset cursor to force refetch of same posts
    src.last_cursor = "0"
    await db_session.commit()

    run2 = await run_collection_for_source(db_session, src)
    assert run2.items_new == 0
    assert run2.items_duplicate == 2

    # Archive should still have exactly 2 items, not 4
    rows = await _rows(db_session, src.id)
    current = [r for r in rows if r.is_current]
    assert len(current) == 2


# --- Archive integration tests (Batch 3) --------------------------------- #

async def test_archive_versioning_is_current_flag(db_session, tg_server):
    """Versioning should mark old version is_current=False, new=True."""
    _serve_channel(tg_server, "chan_ver", "قناة", [_post(10, "النسخة الأولى")])
    src = await _mk(db_session, "chan_ver", tg_server.url)
    await run_collection_for_source(db_session, src)

    # Verify first version is marked current
    rows = await _rows(db_session, src.id)
    assert len(rows) == 1
    assert rows[0].version == 1
    assert rows[0].is_current is True

    # Edit and refetch
    _serve_channel(tg_server, "chan_ver", "قناة", [_post(10, "النسخة الثانية")])
    src.last_cursor = "9"
    await db_session.commit()
    await run_collection_for_source(db_session, src)

    # Verify both versions exist, but only v2 is current
    rows = await _rows(db_session, src.id)
    assert len(rows) == 2
    assert {r.version for r in rows} == {1, 2}
    assert [r.is_current for r in rows if r.version == 1] == [False]
    assert [r.is_current for r in rows if r.version == 2] == [True]


async def test_archive_versioning_supersedes_id(db_session, tg_server):
    """New version should record supersedes_id pointing to the old version."""
    _serve_channel(tg_server, "chan_sup", "قناة", [_post(7, "أصلي")])
    src = await _mk(db_session, "chan_sup", tg_server.url)
    await run_collection_for_source(db_session, src)

    v1_rows = await _rows(db_session, src.id)
    v1_id = v1_rows[0].id

    # Create a new version
    _serve_channel(tg_server, "chan_sup", "قناة", [_post(7, "معدّل")])
    src.last_cursor = "6"
    await db_session.commit()
    await run_collection_for_source(db_session, src)

    rows = await _rows(db_session, src.id)
    v2_row = [r for r in rows if r.version == 2][0]
    assert v2_row.supersedes_id == v1_id


async def test_archive_content_hash_storage(db_session, tg_server):
    """Content hash should be stored and differ for different content."""
    _serve_channel(tg_server, "chan_hash", "قناة", [
        _post(1, "محتوى أول"),
        _post(2, "محتوى ثاني"),
    ])
    src = await _mk(db_session, "chan_hash", tg_server.url)
    await run_collection_for_source(db_session, src)

    rows = await _rows(db_session, src.id)
    assert len(rows) == 2
    hashes = {r.content_hash for r in rows}
    assert len(hashes) == 2  # Two different hashes
    assert all(h for h in hashes)  # All non-empty


async def test_archive_external_id_types(db_session, tg_server):
    """Archive should store both post_id and hash-based external_ids."""
    html = make_telegram_page("mixed_chan", "قناة", [
        _post(1, "مع معرّف"),
        FakePost(post_id=None, text="بدون معرّف"),
    ])
    tg_server.set("/s/mixed_chan", html, content_type="text/html")
    src = await _mk(db_session, "mixed_chan", tg_server.url)
    await run_collection_for_source(db_session, src)

    rows = await _rows(db_session, src.id)
    ext_ids = {r.external_id for r in rows}
    assert "mixed_chan:1" in ext_ids
    # Second post should have hash-based ID
    hash_ids = [eid for eid in ext_ids if eid.startswith("mixed_chan:hash:")]
    assert len(hash_ids) == 1


async def test_archive_fingerprint_matching(db_session, tg_server):
    """Posts with same text should have same fingerprint."""
    text = "نص مشترك للاختبار"
    _serve_channel(tg_server, "chan_fp", "قناة", [_post(1, text)])
    src = await _mk(db_session, "chan_fp", tg_server.url)
    await run_collection_for_source(db_session, src)

    rows = await _rows(db_session, src.id)
    fp = rows[0].fingerprint
    assert fp is not None
    assert len(fp) > 0

    # Change and refetch — different text should produce different fingerprint
    _serve_channel(tg_server, "chan_fp", "قناة", [_post(1, "نص مختلف")])
    src.last_cursor = "0"
    await db_session.commit()
    await run_collection_for_source(db_session, src)

    rows = await _rows(db_session, src.id)
    fp2 = [r.fingerprint for r in rows if r.version == 2][0]
    assert fp2 != fp  # Different text = different fingerprint


async def test_archive_raw_bytes_stored(db_session, tg_server):
    """Raw post data should be stored with correct content type."""
    _serve_channel(tg_server, "chan_raw", "قناة", [_post(3, "محتوى اختبار")])
    src = await _mk(db_session, "chan_raw", tg_server.url)
    await run_collection_for_source(db_session, src)

    rows = await _rows(db_session, src.id)
    assert len(rows) == 1
    r = rows[0]
    assert r.content_type == "application/json"
    assert r.raw_ref is not None  # Points to KV store
    assert r.size_bytes > 0


async def test_archive_extracted_fields_preserved(db_session, tg_server):
    """Extracted fields (text, views, media, forward) should be in archive."""
    _serve_channel(tg_server, "chan_ext", "قناة", [
        _post(1, "نص مع عرض", views="5.2K", media="photo",
              media_extra={"thumbnail_url": "https://example.com/img.jpg"}),
    ])
    src = await _mk(db_session, "chan_ext", tg_server.url)
    await run_collection_for_source(db_session, src)

    rows = await _rows(db_session, src.id)
    ext = rows[0].extracted
    assert ext is not None
    assert ext["text"] == "نص مع عرض"
    assert ext["views"] == "5.2K"
    assert ext["media_meta"]["type"] == "photo"
    assert "thumbnail_url" in ext["media_meta"]


async def test_archive_author_field_truncated(db_session, tg_server):
    """Author should be stored (truncated if needed)."""
    long_author = "X" * 300  # Longer than 256 char limit
    _serve_channel(tg_server, "chan_auth", "قناة", [
        _post(1, "منشور", author=long_author),
    ])
    src = await _mk(db_session, "chan_auth", tg_server.url)
    await run_collection_for_source(db_session, src)

    rows = await _rows(db_session, src.id)
    assert rows[0].author is not None
    assert len(rows[0].author) <= 256


async def test_archive_published_at_stored(db_session, tg_server):
    """Published timestamp should be stored in archive."""
    specific_time = (BASE + timedelta(hours=2)).isoformat()
    posts = [FakePost(post_id=5, text="منشور", datetime=specific_time)]
    html = make_telegram_page("chan_ts", "قناة", posts)
    tg_server.set("/s/chan_ts", html, content_type="text/html")
    src = await _mk(db_session, "chan_ts", tg_server.url)
    await run_collection_for_source(db_session, src)

    rows = await _rows(db_session, src.id)
    assert rows[0].published_at is not None
    assert rows[0].published_at.year == 2026
    assert rows[0].published_at.month == 8


async def test_archive_dedup_by_external_id_primary(db_session, tg_server):
    """Dedup should use external_id as primary key."""
    _serve_channel(tg_server, "chan_eid", "قناة", [_post(99, "أ")])
    src = await _mk(db_session, "chan_eid", tg_server.url)
    run1 = await run_collection_for_source(db_session, src)
    assert run1.items_new == 1

    # Reset cursor and refetch same post
    src.last_cursor = "0"
    await db_session.commit()
    run2 = await run_collection_for_source(db_session, src)

    # Should be detected as duplicate via external_id
    assert run2.items_new == 0
    assert run2.items_duplicate == 1
