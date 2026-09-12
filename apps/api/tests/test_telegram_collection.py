"""Telegram collector tests via a FAKE client (protocol-boundary simulation).

IMPORTANT: these tests do NOT exercise a real Telegram/MTProto connection — the
sandbox has no Telegram access and no credentials. They validate the collector's
logic (initial/incremental/pagination/dedup/edits/flood-wait/reconnect/forwarded/
failure) against a fake adapter. The real Telethon adapter is unit-imported only.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.collection import ContentRelation, RawArchive, Source
from app.modules.collection.runner import run_collection_for_source
from app.modules.collection.storage import reset_store
from app.modules.collection.telegram.client import set_client_override
from app.modules.collection.telegram.fake import FakeTelegramClient
from app.modules.collection.telegram.port import TgChannel, TgMessage

pytestmark = pytest.mark.asyncio(loop_scope="session")

BASE = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)


def msg(mid, text, *, edit=None, fwd_cid=None, fwd_mid=None, media=None):
    return TgMessage(
        message_id=mid, date=BASE + timedelta(minutes=mid), text=text,
        edit_date=edit, fwd_from_channel_id=fwd_cid, fwd_from_message_id=fwd_mid,
        media_meta=media,
    )


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "raw_store_backend", "filesystem")
    monkeypatch.setattr(s, "raw_store_fs_path", str(tmp_path / "tg"))
    monkeypatch.setattr(s, "telegram_flood_sleep_threshold", 5)
    reset_store()
    yield
    set_client_override(None)
    reset_store()


async def _mk(db, username, **over):
    src = Source(
        name=over.get("name", username), source_type="TELEGRAM_PUBLIC",
        url=f"https://t.me/{username}", telegram_username=username,
        language="ar", category="security", source_class="MEDIA_OTHER",
        reliability="C", verification_status="pending", collection_interval_seconds=60,
    )
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return src


def _fake(username, channel_id, messages, **kw):
    ch = TgChannel(channel_id=channel_id, username=username, title=f"Title {username}")
    return FakeTelegramClient({username: ch}, {username: messages}, **kw)


async def _rows(db, sid):
    return list((await db.execute(select(RawArchive).where(RawArchive.source_id == sid))).scalars())


async def test_not_configured_fails_without_fake_data(db_session):
    set_client_override(None)  # no client, no creds
    src = await _mk(db_session, "chan_a")
    run = await run_collection_for_source(db_session, src)
    assert run.status == "failure"
    assert "configured" in (src.last_error or "").lower()
    assert len(await _rows(db_session, src.id)) == 0  # no fabricated posts


async def test_initial_collection_and_verification(db_session):
    set_client_override(_fake("chan_b", 111, [msg(1, "منشور ١"), msg(2, "منشور ٢"), msg(3, "منشور ٣")]))
    src = await _mk(db_session, "chan_b")
    run = await run_collection_for_source(db_session, src)
    assert run.status == "success" and run.items_new == 3
    await db_session.refresh(src)
    assert src.telegram_channel_id == 111
    assert src.verification_status == "verified" and src.verified_at is not None
    assert src.last_cursor == "3"
    rows = await _rows(db_session, src.id)
    assert {r.external_id for r in rows} == {"111:1", "111:2", "111:3"}
    assert rows[0].canonical_url.startswith("https://t.me/chan_b/")


async def test_incremental_only_new(db_session):
    msgs = [msg(1, "أ"), msg(2, "ب")]
    set_client_override(_fake("chan_c", 222, msgs))
    src = await _mk(db_session, "chan_c")
    await run_collection_for_source(db_session, src)
    # Add newer messages; only those beyond the cursor are collected.
    msgs.extend([msg(3, "ج"), msg(4, "د")])
    run2 = await run_collection_for_source(db_session, src)
    assert run2.items_new == 2 and run2.items_seen == 2
    await db_session.refresh(src)
    assert src.last_cursor == "4"


async def test_duplicate_when_cursor_reset(db_session):
    msgs = [msg(1, "أ"), msg(2, "ب"), msg(3, "ج")]
    set_client_override(_fake("chan_d", 333, msgs))
    src = await _mk(db_session, "chan_d")
    await run_collection_for_source(db_session, src)
    src.last_cursor = "0"  # force refetch of the same messages
    await db_session.commit()
    run2 = await run_collection_for_source(db_session, src)
    assert run2.items_new == 0 and run2.items_duplicate == 3


async def test_edited_message_versioning(db_session):
    m = msg(5, "النص الأصلي")
    fake = _fake("chan_e", 444, [m])
    set_client_override(fake)
    src = await _mk(db_session, "chan_e")
    await run_collection_for_source(db_session, src)
    # Edit the message and refetch it.
    m.text = "النص بعد التعديل الجوهري"
    m.edit_date = BASE + timedelta(hours=1)
    src.last_cursor = "4"
    await db_session.commit()
    run2 = await run_collection_for_source(db_session, src)
    assert run2.items_versioned == 1
    rows = await _rows(db_session, src.id)
    assert {r.version for r in rows} == {1, 2}


async def test_flood_wait_is_handled(db_session):
    set_client_override(_fake("chan_f", 555, [msg(1, "x"), msg(2, "y")], flood_once=True))
    src = await _mk(db_session, "chan_f")
    run = await run_collection_for_source(db_session, src)
    assert run.status == "success" and run.items_new == 2  # recovered after wait


async def test_graceful_reconnect(db_session):
    fake = _fake("chan_g", 666, [msg(1, "z")], connect_fail_times=1)
    set_client_override(fake)
    src = await _mk(db_session, "chan_g")
    run = await run_collection_for_source(db_session, src)
    assert run.status == "success" and run.items_new == 1
    assert fake.connect_calls == 2  # failed once, retried, succeeded


async def test_resolve_failure(db_session):
    set_client_override(_fake("known", 777, [msg(1, "a")]))
    src = await _mk(db_session, "unknown_channel")  # not in fake -> resolve fails
    run = await run_collection_for_source(db_session, src)
    assert run.status == "failure"
    assert len(await _rows(db_session, src.id)) == 0


async def test_forwarded_from_relation(db_session):
    # Channel A has message 10; Channel B forwards it.
    set_client_override(_fake("orig", 888, [msg(10, "خبر أصلي")]))
    a = await _mk(db_session, "orig")
    await run_collection_for_source(db_session, a)

    set_client_override(_fake("reposter", 999, [msg(1, "منقول", fwd_cid=888, fwd_mid=10)]))
    b = await _mk(db_session, "reposter")
    await run_collection_for_source(db_session, b)

    rels = (await db_session.execute(
        select(func.count()).select_from(ContentRelation)
        .where(ContentRelation.relation_type == "forwarded_from")
    )).scalar_one()
    assert rels >= 1


async def test_media_metadata_archived(db_session):
    set_client_override(_fake("chan_m", 1010, [msg(1, "بصورة", media={"type": "photo"})]))
    src = await _mk(db_session, "chan_m")
    await run_collection_for_source(db_session, src)
    rows = await _rows(db_session, src.id)
    assert rows[0].extracted["media_meta"] == {"type": "photo"}
