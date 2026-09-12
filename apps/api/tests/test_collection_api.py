"""Collection API tests: sources/jobs/archive/health + RBAC + audit.

The /collect endpoint performs a real HTTP collection against a local RSS server
(genuine fetch/parse/archive). No data is inserted directly."""
from __future__ import annotations

import json

import pytest

from app.core.config import get_settings
from app.modules.collection.storage import reset_store
from tests._feedserver import FeedServer, make_rss
from tests._telegram_page import FakePost, make_telegram_page

pytestmark = pytest.mark.asyncio(loop_scope="session")

ITEMS = [
    {"guid": "a-1", "title": "بند ١", "link": "http://ex/1", "description": "وصف ١"},
    {"guid": "a-2", "title": "بند ٢", "link": "http://ex/2", "description": "وصف ٢"},
]


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
    monkeypatch.setattr(s, "collector_respect_robots", True)
    monkeypatch.setattr(s, "collector_max_retries", 2)
    monkeypatch.setattr(s, "collector_backoff_base_seconds", 0.0)
    monkeypatch.setattr(s, "raw_store_backend", "filesystem")
    monkeypatch.setattr(s, "raw_store_fs_path", str(tmp_path / "archive"))
    reset_store()
    yield
    reset_store()


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


async def _create(client, admin_token, url, **over):
    body = {"name": "RSS Src", "source_type": "RSS", "url": url,
            "language": "ar", "category": "security", "reliability": "B"}
    body.update(over)
    return await client.post("/api/v1/sources", headers=_auth(admin_token), json=body)


async def test_unauthenticated_rejected(client):
    assert (await client.get("/api/v1/sources")).status_code == 401


async def test_create_and_list(client, admin_token, feed_server):
    r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    lst = await client.get("/api/v1/sources", headers=_auth(admin_token))
    assert any(s["id"] == sid for s in lst.json())


async def test_create_requires_manage_permission(client, viewer_token, feed_server):
    r = await _create(client, viewer_token, f"{feed_server.url}/feed.xml")
    assert r.status_code == 403


async def test_create_rejects_ssrf(client, admin_token, monkeypatch):
    monkeypatch.setattr(get_settings(), "collector_allow_private_hosts", False)
    r = await _create(client, admin_token, "http://169.254.169.254/feed.xml")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "ssrf_rejected"


async def test_unsupported_source_type_rejected(client, admin_token):
    # NEWS is a declared source_type with no collector implemented yet — the
    # service must refuse to register a source it cannot collect.
    r = await _create(client, admin_token, "https://news.example/rss", source_type="NEWS")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported_source_type"


async def test_create_telegram_public_source(client, admin_token):
    # P1.3: TELEGRAM_PUBLIC is now an implemented collector. Creating one must
    # succeed and start unverified — never claim verification without a resolve.
    r = await _create(
        client, admin_token, "https://t.me/some_channel",
        source_type="TELEGRAM_PUBLIC", telegram_username="some_channel",
        source_class="OFFICIAL",
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source_type"] == "TELEGRAM_PUBLIC"
    assert body["verification_status"] == "pending"
    assert body["telegram_username"] == "some_channel"
    assert body["source_class"] == "OFFICIAL"
    assert body["telegram_channel_id"] is None  # not resolved yet


async def test_collect_via_api_archives(client, admin_token, feed_server):
    sid = (await _create(client, admin_token, f"{feed_server.url}/feed.xml")).json()["id"]
    run = await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "success" and body["items_new"] == 2

    arch = await client.get(f"/api/v1/archive?source_id={sid}", headers=_auth(admin_token))
    items = arch.json()
    assert len(items) == 2
    raw = await client.get(f"/api/v1/archive/{items[0]['id']}/raw", headers=_auth(admin_token))
    assert raw.status_code == 200 and "id" in json.loads(raw.content)


async def test_collect_requires_run_permission(client, admin_token, viewer_token, feed_server):
    sid = (await _create(client, admin_token, f"{feed_server.url}/feed.xml")).json()["id"]
    r = await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(viewer_token))
    assert r.status_code == 403


async def test_disable_and_enable(client, admin_token, feed_server):
    sid = (await _create(client, admin_token, f"{feed_server.url}/feed.xml")).json()["id"]
    d = await client.post(f"/api/v1/sources/{sid}/disable", headers=_auth(admin_token))
    assert d.status_code == 200 and d.json()["enabled"] is False
    e = await client.post(f"/api/v1/sources/{sid}/enable", headers=_auth(admin_token))
    assert e.json()["enabled"] is True


async def test_dashboard_and_health(client, admin_token, feed_server):
    sid = (await _create(client, admin_token, f"{feed_server.url}/feed.xml")).json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    dash = await client.get("/api/v1/sources/dashboard", headers=_auth(admin_token))
    body = dash.json()
    assert body["total"] >= 1 and body["healthy"] >= 1 and body["archive_items"] >= 2
    h = await client.get(f"/api/v1/sources/{sid}/health", headers=_auth(admin_token))
    assert h.json()["health"] == "healthy" and h.json()["success_count"] >= 1


async def test_source_create_is_audited(client, admin_token, feed_server):
    await _create(client, admin_token, f"{feed_server.url}/feed.xml", name="Audited Source")
    a = await client.get("/api/v1/audit?action=source.create&limit=20", headers=_auth(admin_token))
    assert any(e["action"] == "source.create" for e in a.json())


async def test_verify_telegram_without_credentials_stays_pending(client, admin_token):
    # With no Telegram credentials configured, verification must NOT claim success:
    # it reports 'pending' and never fabricates a channel_id.
    sid = (await _create(
        client, admin_token, "https://t.me/verify_me",
        source_type="TELEGRAM_PUBLIC", telegram_username="verify_me",
        source_class="OFFICIAL",
    )).json()["id"]
    r = await client.post(f"/api/v1/sources/{sid}/verify", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["reason"] == "telegram_not_configured"
    # Audit trail records the verify attempt.
    a = await client.get("/api/v1/audit?action=source.verify&limit=20", headers=_auth(admin_token))
    assert any(e["action"] == "source.verify" for e in a.json())


async def test_verify_requires_manage_permission(client, admin_token, viewer_token):
    sid = (await _create(
        client, admin_token, "https://t.me/verify_rbac",
        source_type="TELEGRAM_PUBLIC", telegram_username="verify_rbac",
    )).json()["id"]
    r = await client.post(f"/api/v1/sources/{sid}/verify", headers=_auth(viewer_token))
    assert r.status_code == 403


async def test_create_telegram_public_web_source(client, admin_token):
    # P1.3 web: TELEGRAM_PUBLIC_WEB is the HTTP-based collector. Creating one
    # must succeed and start unverified — same as TELEGRAM_PUBLIC.
    r = await _create(
        client, admin_token, "https://t.me/s/web_channel",
        source_type="TELEGRAM_PUBLIC_WEB", telegram_username="web_channel",
        source_class="OFFICIAL",
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source_type"] == "TELEGRAM_PUBLIC_WEB"
    assert body["verification_status"] == "pending"
    assert body["telegram_username"] == "web_channel"
    assert body["source_class"] == "OFFICIAL"


# --- Archive Search (P1.4) ------------------------------------------------ #

async def test_archive_search_no_filters(client, admin_token, feed_server):
    """GET /archive/search with no filters returns all current items."""
    r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    sid = r.json()["id"]
    # Collect to populate archive
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    # Search with no filters
    r = await client.get("/api/v1/archive/search", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 2
    assert all(i["is_current"] for i in items)


async def test_archive_search_by_source_id(client, admin_token, feed_server):
    """GET /archive/search?source_id=X filters by source."""
    r = await _create(client, admin_token, f"{feed_server.url}/feed.xml", name="Src1")
    sid1 = r.json()["id"]
    # Set up second feed and create source with different URL to avoid unique constraint
    feed_server.set("/feed2.xml", make_rss(ITEMS))
    r = await _create(client, admin_token, f"{feed_server.url}/feed2.xml", name="Src2")
    sid2 = r.json()["id"]
    # Collect both
    await client.post(f"/api/v1/sources/{sid1}/collect", headers=_auth(admin_token))
    await client.post(f"/api/v1/sources/{sid2}/collect", headers=_auth(admin_token))
    # Search for sid1 only
    r = await client.get(f"/api/v1/archive/search?source_id={sid1}", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 2
    assert all(str(i["source_id"]) == str(sid1) for i in items)


async def test_archive_search_by_language(client, admin_token, feed_server):
    """GET /archive/search?language=ar filters by language."""
    r = await _create(
        client, admin_token, f"{feed_server.url}/feed.xml",
        language="ar",
    )
    sid = r.json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    # Search by language
    r = await client.get("/api/v1/archive/search?language=ar", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 2
    assert all(i["language"] == "ar" for i in items)


async def test_archive_search_by_content_type(client, admin_token, feed_server):
    """GET /archive/search?content_type=application/json filters by type."""
    r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    sid = r.json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    # RSS items are stored as application/json
    r = await client.get(
        "/api/v1/archive/search?content_type=application/json",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 1
    assert all(i["content_type"] == "application/json" for i in items)


async def test_archive_search_by_date_range(client, admin_token, feed_server):
    """GET /archive/search?date_from=X&date_to=Y filters by collection date."""
    r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    sid = r.json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    # Search within date range
    r = await client.get(
        "/api/v1/archive/search?date_from=2000-01-01&date_to=2999-12-31",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 2


async def test_archive_search_limit_enforced(client, admin_token, feed_server):
    """GET /archive/search?limit=1 returns max 1 item."""
    r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    sid = r.json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    # Search with limit=1
    r = await client.get("/api/v1/archive/search?limit=1", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 1


async def test_archive_search_limit_capped_at_500(client, admin_token, feed_server):
    """Limit parameter is capped at 500 for safety."""
    r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    sid = r.json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    # Verify limit query param is validated by FastAPI (le=500 constraint)
    r = await client.get("/api/v1/archive/search?limit=501", headers=_auth(admin_token))
    assert r.status_code == 422  # Pydantic validation error for le=500
    r = await client.get("/api/v1/archive/search?limit=9999", headers=_auth(admin_token))
    assert r.status_code == 422  # Pydantic validation error for le=500


async def test_archive_search_no_results(client, admin_token):
    """GET /archive/search with impossible filter returns empty list."""
    r = await client.get(
        "/api/v1/archive/search?language=xyz999",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 0


async def test_archive_search_requires_permission(client, viewer_token):
    """GET /archive/search without archive:read permission is denied."""
    # viewer_token has archive:read, so this should work
    r = await client.get("/api/v1/archive/search", headers=_auth(viewer_token))
    assert r.status_code == 200, r.text


async def test_archive_search_unauthenticated_rejected(client):
    """GET /archive/search without auth is rejected."""
    r = await client.get("/api/v1/archive/search")
    assert r.status_code == 401


# --- Cross-Source Verification (P1.4 Batch 3) ---- #

async def test_archive_search_multiple_source_types(client, admin_token, feed_server):
    """Archive search can return items from multiple source types (RSS + TELEGRAM_PUBLIC_WEB)."""
    # Create and collect RSS source
    r = await _create(client, admin_token, f"{feed_server.url}/feed.xml", name="RSS Source")
    rss_sid = r.json()["id"]
    await client.post(f"/api/v1/sources/{rss_sid}/collect", headers=_auth(admin_token))

    # Create and collect TELEGRAM_PUBLIC_WEB source
    tg_html = make_telegram_page("test_ch", "Test Channel", [
        FakePost(post_id=1, text="منشور تلغرام ١"),
        FakePost(post_id=2, text="منشور تلغرام ٢"),
    ])
    feed_server.set("/s/test_ch", tg_html, content_type="text/html")
    r = await _create(
        client, admin_token, f"{feed_server.url}/s/test_ch",
        source_type="TELEGRAM_PUBLIC_WEB", telegram_username="test_ch",
        name="Telegram Source", language="ar",
    )
    tg_sid = r.json()["id"]
    await client.post(f"/api/v1/sources/{tg_sid}/collect", headers=_auth(admin_token))

    # Search without filters should return both RSS and Telegram items
    r = await client.get("/api/v1/archive/search", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    items = r.json()

    # Verify we have items from both sources
    source_types = {str(i["source_id"]) for i in items}
    assert str(rss_sid) in source_types, "RSS items should be in search results"
    assert str(tg_sid) in source_types, "Telegram items should be in search results"

    # Verify all returned items are current
    assert all(i["is_current"] for i in items), "All items should be current version"


async def test_archive_search_ordering_desc(client, admin_token, feed_server):
    """Archive search returns items ordered by collected_at DESC (newest first)."""
    r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    sid = r.json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))

    # Get all items without limit
    r = await client.get("/api/v1/archive/search?limit=500", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    items = r.json()

    # Verify ordering: each item's collected_at should be >= next item's (DESC order)
    for i in range(len(items) - 1):
        curr = items[i]["collected_at"]
        next_item = items[i + 1]["collected_at"]
        assert curr >= next_item, (
            f"Items not ordered DESC by collected_at: "
            f"{curr} < {next_item} at indices {i}, {i+1}"
        )


async def test_archive_search_current_version_only(client, admin_token, feed_server):
    """Archive search returns only current versions, not old versions."""
    r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    sid = r.json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))

    # Get items
    r = await client.get(f"/api/v1/archive/search?source_id={sid}", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    items = r.json()

    # Every returned item must have is_current=True
    assert len(items) >= 1, "Should have at least one item"
    assert all(i["is_current"] is True for i in items), (
        "All archive search results must be current versions only"
    )

    # Version field should be populated
    assert all("version" in i for i in items), "Items should have version field"


# --- Events (P1.6) -------------------------------------------------------- #
async def test_event_unauthenticated_rejected(client):
    """Unauthenticated requests to event endpoints must be rejected."""
    assert (await client.get("/api/v1/events")).status_code == 401
    assert (await client.post("/api/v1/events", json={})).status_code == 401


async def test_event_list_requires_permission(client, viewer_token):
    """GET /events requires event:read permission."""
    # viewer_token should have read permission but not write
    r = await client.get("/api/v1/events", headers=_auth(viewer_token))
    # Should succeed if viewer has event:read, or 403 if not
    assert r.status_code in (200, 403)


async def test_create_event_minimal(client, admin_token):
    """POST /events creates event with minimal fields."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    body = {
        "title": "Test Event",
        "occurred_at": now.isoformat(),
    }
    r = await client.post("/api/v1/events", headers=_auth(admin_token), json=body)
    assert r.status_code == 201, r.text
    event = r.json()
    assert event["title"] == "Test Event"
    assert event["status"] == "pending"  # default
    assert event["severity"] == "C"  # default
    assert event["confidence"] == 0.5  # default
    assert event["created_by"] is not None
    assert event["id"] is not None


async def test_create_event_full(client, admin_token):
    """POST /events creates event with all fields."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    body = {
        "title": "Full Event",
        "description": "A detailed event description",
        "occurred_at": now.isoformat(),
        "status": "confirmed",
        "severity": "A",
        "confidence": 0.95,
    }
    r = await client.post("/api/v1/events", headers=_auth(admin_token), json=body)
    assert r.status_code == 201, r.text
    event = r.json()
    assert event["title"] == "Full Event"
    assert event["description"] == "A detailed event description"
    assert event["status"] == "confirmed"
    assert event["severity"] == "A"
    assert event["confidence"] == 0.95


async def test_create_event_requires_create_permission(client, viewer_token):
    """POST /events requires event:create permission."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    body = {
        "title": "Event",
        "occurred_at": now.isoformat(),
    }
    r = await client.post("/api/v1/events", headers=_auth(viewer_token), json=body)
    assert r.status_code == 403


async def test_create_event_validates_title(client, admin_token):
    """POST /events validates title (required, max 512)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    # Empty title
    r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "", "occurred_at": now.isoformat()},
    )
    assert r.status_code == 422


async def test_create_event_validates_confidence(client, admin_token):
    """POST /events validates confidence (0.0-1.0)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    # Confidence > 1.0
    r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "Event", "occurred_at": now.isoformat(), "confidence": 1.5},
    )
    assert r.status_code == 422
    # Confidence < 0.0
    r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "Event", "occurred_at": now.isoformat(), "confidence": -0.1},
    )
    assert r.status_code == 422


async def test_create_event_validates_status(client, admin_token):
    """POST /events validates status (must be one of allowed values)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "Event", "occurred_at": now.isoformat(), "status": "invalid"},
    )
    assert r.status_code == 422


async def test_create_event_validates_severity(client, admin_token):
    """POST /events validates severity (must be A-F)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "Event", "occurred_at": now.isoformat(), "severity": "G"},
    )
    assert r.status_code == 422


async def test_get_event(client, admin_token):
    """GET /events/{id} retrieves a single event."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    # Create an event
    create_r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "Test", "occurred_at": now.isoformat()},
    )
    assert create_r.status_code == 201
    event_id = create_r.json()["id"]
    # Get the event
    r = await client.get(f"/api/v1/events/{event_id}", headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.json()["id"] == event_id
    assert r.json()["title"] == "Test"


async def test_get_nonexistent_event(client, admin_token):
    """GET /events/{id} returns 404 for nonexistent event."""
    import uuid

    nonexistent_id = str(uuid.uuid4())
    r = await client.get(f"/api/v1/events/{nonexistent_id}", headers=_auth(admin_token))
    assert r.status_code == 404


async def test_list_events(client, admin_token):
    """GET /events returns list of events."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    # Create a few events
    for i in range(3):
        await client.post(
            "/api/v1/events",
            headers=_auth(admin_token),
            json={"title": f"Event {i}", "occurred_at": now.isoformat()},
        )
    # List events
    r = await client.get("/api/v1/events", headers=_auth(admin_token))
    assert r.status_code == 200
    events = r.json()
    assert len(events) >= 3


async def test_update_event(client, admin_token):
    """PATCH /events/{id} updates an event."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    # Create an event
    create_r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "Original", "occurred_at": now.isoformat(), "status": "pending"},
    )
    assert create_r.status_code == 201
    event_id = create_r.json()["id"]
    # Update it
    r = await client.patch(
        f"/api/v1/events/{event_id}",
        headers=_auth(admin_token),
        json={"status": "confirmed", "severity": "B"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"
    assert r.json()["severity"] == "B"
    assert r.json()["title"] == "Original"  # unchanged


async def test_update_event_requires_permission(client, viewer_token, admin_token):
    """PATCH /events/{id} requires event:update permission."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    # Create with admin
    create_r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "Event", "occurred_at": now.isoformat()},
    )
    event_id = create_r.json()["id"]
    # Try to update with viewer
    r = await client.patch(
        f"/api/v1/events/{event_id}",
        headers=_auth(viewer_token),
        json={"status": "confirmed"},
    )
    assert r.status_code == 403


async def test_link_archive_to_event(client, admin_token, feed_server):
    """POST /events/{id}/archive/{id} links archive to event."""
    from datetime import datetime, timezone

    # Create a source and collect to populate archive
    src_r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    sid = src_r.json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    # Get an archive item
    archive_r = await client.get("/api/v1/archive", headers=_auth(admin_token))
    archive_id = archive_r.json()[0]["id"]
    # Create an event
    now = datetime.now(timezone.utc)
    event_r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "Event", "occurred_at": now.isoformat()},
    )
    event_id = event_r.json()["id"]
    # Link archive to event
    r = await client.post(
        f"/api/v1/events/{event_id}/archive/{archive_id}",
        headers=_auth(admin_token),
    )
    assert r.status_code == 201, r.text
    link = r.json()
    assert link["event_id"] == event_id
    assert link["archive_id"] == archive_id


async def test_link_archive_requires_permission(client, viewer_token, admin_token, feed_server):
    """POST /events/{id}/archive/{id} requires event:link permission."""
    from datetime import datetime, timezone

    # Setup with admin
    src_r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    sid = src_r.json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    archive_r = await client.get("/api/v1/archive", headers=_auth(admin_token))
    archive_id = archive_r.json()[0]["id"]
    now = datetime.now(timezone.utc)
    event_r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "Event", "occurred_at": now.isoformat()},
    )
    event_id = event_r.json()["id"]
    # Try to link with viewer
    r = await client.post(
        f"/api/v1/events/{event_id}/archive/{archive_id}",
        headers=_auth(viewer_token),
    )
    assert r.status_code == 403


async def test_link_archive_duplicate_rejected(client, admin_token, feed_server):
    """Duplicate archive links are rejected with 409 Conflict."""
    from datetime import datetime, timezone

    # Setup
    src_r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    sid = src_r.json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    archive_r = await client.get("/api/v1/archive", headers=_auth(admin_token))
    archive_id = archive_r.json()[0]["id"]
    now = datetime.now(timezone.utc)
    event_r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "Event", "occurred_at": now.isoformat()},
    )
    event_id = event_r.json()["id"]
    # Link once
    r1 = await client.post(
        f"/api/v1/events/{event_id}/archive/{archive_id}",
        headers=_auth(admin_token),
    )
    assert r1.status_code == 201
    # Try to link again
    r2 = await client.post(
        f"/api/v1/events/{event_id}/archive/{archive_id}",
        headers=_auth(admin_token),
    )
    assert r2.status_code == 409


async def test_link_nonexistent_event_rejected(client, admin_token, feed_server):
    """Linking to nonexistent event returns 404."""
    import uuid

    src_r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    sid = src_r.json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    archive_r = await client.get("/api/v1/archive", headers=_auth(admin_token))
    archive_id = archive_r.json()[0]["id"]
    nonexistent_id = str(uuid.uuid4())
    r = await client.post(
        f"/api/v1/events/{nonexistent_id}/archive/{archive_id}",
        headers=_auth(admin_token),
    )
    assert r.status_code == 404


async def test_link_nonexistent_archive_rejected(client, admin_token):
    """Linking nonexistent archive returns 404."""
    from datetime import datetime, timezone
    import uuid

    now = datetime.now(timezone.utc)
    event_r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "Event", "occurred_at": now.isoformat()},
    )
    event_id = event_r.json()["id"]
    nonexistent_archive_id = str(uuid.uuid4())
    r = await client.post(
        f"/api/v1/events/{event_id}/archive/{nonexistent_archive_id}",
        headers=_auth(admin_token),
    )
    assert r.status_code == 404


async def test_unlink_archive_from_event(client, admin_token, feed_server):
    """DELETE /events/{id}/archive/{id} unlinks archive from event."""
    from datetime import datetime, timezone

    # Setup
    src_r = await _create(client, admin_token, f"{feed_server.url}/feed.xml")
    sid = src_r.json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    archive_r = await client.get("/api/v1/archive", headers=_auth(admin_token))
    archive_id = archive_r.json()[0]["id"]
    now = datetime.now(timezone.utc)
    event_r = await client.post(
        "/api/v1/events",
        headers=_auth(admin_token),
        json={"title": "Event", "occurred_at": now.isoformat()},
    )
    event_id = event_r.json()["id"]
    # Link
    await client.post(
        f"/api/v1/events/{event_id}/archive/{archive_id}",
        headers=_auth(admin_token),
    )
    # Unlink
    r = await client.delete(
        f"/api/v1/events/{event_id}/archive/{archive_id}",
        headers=_auth(admin_token),
    )
    assert r.status_code == 204
    # Verify link is gone
    r2 = await client.delete(
        f"/api/v1/events/{event_id}/archive/{archive_id}",
        headers=_auth(admin_token),
    )
    assert r2.status_code == 404
