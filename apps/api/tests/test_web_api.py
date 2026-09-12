"""Web-source API: create WEBSITE sources, collect, extracted view, relations,
cancel — all RBAC-gated and audited."""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.modules.collection.storage import reset_store
from tests._feedserver import FeedServer

pytestmark = pytest.mark.asyncio(loop_scope="session")


def article_html(title, body, canonical):
    return f"""<!doctype html><html lang="ar"><head>
<meta property="og:title" content="{title}"><meta name="author" content="محرر">
<link rel="canonical" href="{canonical}"></head>
<body><article><h1>{title}</h1><p>{body}</p></article></body></html>"""


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


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


async def _web_source(client, token, url, **over):
    body = {"name": "Web Src", "source_type": "WEBSITE", "url": url,
            "language": "ar", "category": "security",
            "extraction_config": {"mode": "article"}}
    body.update(over)
    return await client.post("/api/v1/sources", headers=_auth(token), json=body)


async def test_create_website_source_requires_manage(client, viewer_token, server):
    server.set("/s", article_html("ع", "متن كافٍ للطول", "http://x/s"), "text/html")
    r = await _web_source(client, viewer_token, f"{server.url}/s")
    assert r.status_code == 403


async def test_collect_website_and_view_extracted(client, admin_token, server):
    server.set("/story", article_html("عنوان الويب", "متن مقال الويب الطويل والحقيقي", "http://x/story"), "text/html")
    sid = (await _web_source(client, admin_token, f"{server.url}/story")).json()["id"]
    run = await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    assert run.status_code == 200 and run.json()["items_new"] == 1
    items = (await client.get(f"/api/v1/archive?source_id={sid}", headers=_auth(admin_token))).json()
    assert len(items) == 1 and items[0]["author"] == "محرر"
    ex = await client.get(f"/api/v1/archive/{items[0]['id']}/extracted", headers=_auth(admin_token))
    assert ex.status_code == 200 and "متن مقال الويب" in ex.json()["extracted"]["body"]


async def test_same_event_relations_via_api(client, admin_token, server):
    title, body = "خبر منسوخ", "نص منسوخ حرفياً بين مصدرين اثنين حول الحدث ذاته"
    server.set("/wa", article_html(title, body, "http://a/1"), "text/html")
    server.set("/wb", article_html(title, body, "http://b/1"), "text/html")
    sa = (await _web_source(client, admin_token, f"{server.url}/wa", name="WA")).json()["id"]
    sb = (await _web_source(client, admin_token, f"{server.url}/wb", name="WB")).json()["id"]
    await client.post(f"/api/v1/sources/{sa}/collect", headers=_auth(admin_token))
    await client.post(f"/api/v1/sources/{sb}/collect", headers=_auth(admin_token))
    items_b = (await client.get(f"/api/v1/archive?source_id={sb}", headers=_auth(admin_token))).json()
    rels = await client.get(f"/api/v1/archive/{items_b[0]['id']}/relations", headers=_auth(admin_token))
    assert rels.status_code == 200
    assert any(r["relation_type"] == "same_event_candidate" for r in rels.json())


async def test_cancel_endpoint_rbac_and_audit(client, admin_token, viewer_token, server):
    server.set("/c", article_html("ع", "متن", "http://x/c"), "text/html")
    sid = (await _web_source(client, admin_token, f"{server.url}/c")).json()["id"]
    # viewer cannot cancel
    assert (await client.post(f"/api/v1/sources/{sid}/cancel", headers=_auth(viewer_token))).status_code == 403
    # admin can
    c = await client.post(f"/api/v1/sources/{sid}/cancel", headers=_auth(admin_token))
    assert c.status_code == 202 and c.json()["status"] == "cancel_requested"
    audit = await client.get("/api/v1/audit?action=collection.cancel", headers=_auth(admin_token))
    assert any(e["action"] == "collection.cancel" for e in audit.json())


async def test_run_exposes_web_counters(client, admin_token, server):
    server.set("/r", article_html("ع", "متن كافٍ", "http://x/r"), "text/html")
    sid = (await _web_source(client, admin_token, f"{server.url}/r")).json()["id"]
    await client.post(f"/api/v1/sources/{sid}/collect", headers=_auth(admin_token))
    runs = (await client.get(f"/api/v1/sources/{sid}/runs", headers=_auth(admin_token))).json()
    assert runs and "items_discovered" in runs[0] and "items_failed" in runs[0]
