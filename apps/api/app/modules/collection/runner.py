"""Collection runner: executes one collection for a source and records
everything — the raw archive (with dedup + versioning), the run history, and the
source health counters. Used by both the API trigger and the scheduled worker.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.collection.rss  # noqa: F401  (registers RssCollector)
import app.modules.collection.telegram.collector  # noqa: F401  (registers TelegramCollector)
import app.modules.collection.telegram_web.collector  # noqa: F401  (registers TelegramWebCollector)
import app.modules.collection.web  # noqa: F401  (registers WebsiteCollector)
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.ssrf import SSRFError
from app.models.collection import CollectionRun, ContentRelation, RawArchive, Source
from app.modules.collection.base import CollectedItem, CollectResult, get_collector
from app.modules.collection.fingerprint import content_hash, fingerprint
from app.modules.collection.storage import get_store


def _cancel_key(run_id: uuid.UUID) -> str:
    return f"cancel:run:{run_id}"


def _cancel_source_key(source_id: uuid.UUID) -> str:
    return f"cancel:source:{source_id}"


async def request_cancel(run_id: uuid.UUID) -> None:
    """Signal an in-progress run to stop (checked between articles in index mode)."""
    try:
        await get_redis().set(_cancel_key(run_id), "1", ex=3600)
    except Exception as exc:  # noqa: BLE001
        log.warning("cancel_signal_failed", run=str(run_id), error=str(exc))


async def request_cancel_source(source_id: uuid.UUID) -> None:
    """Signal the source's in-progress run to stop."""
    try:
        await get_redis().set(_cancel_source_key(source_id), "1", ex=3600)
    except Exception as exc:  # noqa: BLE001
        log.warning("cancel_signal_failed", source=str(source_id), error=str(exc))

log = get_logger("runner")


def _now() -> datetime:
    return datetime.now(tz=UTC)


async def _current_archive(
    db: AsyncSession, source_id: uuid.UUID, external_id: str, canonical_url: str | None
) -> RawArchive | None:
    stmt = select(RawArchive).where(
        RawArchive.source_id == source_id,
        RawArchive.is_current.is_(True),
    )
    if external_id:
        stmt = stmt.where(RawArchive.external_id == external_id)
    elif canonical_url:
        stmt = stmt.where(RawArchive.canonical_url == canonical_url)
    else:
        return None
    stmt = stmt.order_by(RawArchive.version.desc()).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _insert_version(
    db: AsyncSession,
    source: Source,
    item: CollectedItem,
    ch: str,
    fp: str,
    *,
    version: int,
    supersedes: uuid.UUID | None,
    http_status: int | None,
    ip: str | None,
) -> RawArchive:
    store = get_store()
    key = store.key_for(str(source.id), ch)
    await asyncio.to_thread(store.put, key, item.raw_bytes, item.content_type)
    row = RawArchive(
        source_id=source.id,
        url=item.url,
        canonical_url=item.canonical_url,
        external_id=item.external_id,
        title=(item.title or "")[:1024] or None,
        author=(item.author or "")[:256] or None,
        extracted=item.extracted,
        published_at=item.published_at,
        collected_at=_now(),
        content_type=item.content_type,
        language=item.language,
        content_hash=ch,
        fingerprint=fp,
        version=version,
        supersedes_id=supersedes,
        is_current=True,
        http_status=http_status,
        http_headers={},
        ip_address=ip,
        size_bytes=len(item.raw_bytes),
        raw_ref=key,
    )
    db.add(row)
    await db.flush()
    return row


async def _link_same_event(db: AsyncSession, new_row: RawArchive) -> int:
    """Record same_event_candidate relations to current items from OTHER sources
    that share this normalized fingerprint. Never deletes/merges — links only."""
    if not new_row.fingerprint:
        return 0
    others = (
        await db.execute(
            select(RawArchive).where(
                RawArchive.fingerprint == new_row.fingerprint,
                RawArchive.is_current.is_(True),
                RawArchive.source_id != new_row.source_id,
                RawArchive.id != new_row.id,
            )
        )
    ).scalars().all()
    linked = 0
    for other in others:
        db.add(
            ContentRelation(
                from_archive_id=new_row.id,
                to_archive_id=other.id,
                relation_type="same_event_candidate",
                similarity=1.0,
            )
        )
        linked += 1
    if linked:
        await db.flush()
    return linked


async def _link_forwarded(db: AsyncSession, new_row: RawArchive, item: CollectedItem) -> None:
    """If a post is a public forward of a message we've already archived, record a
    forwarded_from relation to the original (never treat it as an independent event)."""
    fwd = (item.extracted or {}).get("forward") if item.extracted else None
    if not fwd or not fwd.get("channel_id") or not fwd.get("message_id"):
        return
    original_ext = f"{fwd['channel_id']}:{fwd['message_id']}"
    original = (
        await db.execute(
            select(RawArchive).where(
                RawArchive.external_id == original_ext,
                RawArchive.is_current.is_(True),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if original is None or original.id == new_row.id:
        return
    db.add(
        ContentRelation(
            from_archive_id=new_row.id,
            to_archive_id=original.id,
            relation_type="forwarded_from",
            similarity=1.0,
        )
    )
    await db.flush()


def _mark_success(source: Source, latency_ms: int, result: CollectResult) -> None:
    source.total_runs += 1
    source.success_count += 1
    source.consecutive_failures = 0
    source.last_success_at = _now()
    source.last_status = "success"
    source.last_error = None
    source.avg_latency_ms = (
        latency_ms if source.total_runs <= 1
        else round(0.7 * source.avg_latency_ms + 0.3 * latency_ms, 1)
    )
    if result.etag:
        source.etag = result.etag[:512]
    if result.last_modified:
        source.last_modified = result.last_modified[:128]


def _mark_failure(source: Source, run: CollectionRun, error: str) -> None:
    run.status = "failure"
    run.error = error[:1024]
    source.total_runs += 1
    source.failure_count += 1
    source.consecutive_failures += 1
    source.last_failure_at = _now()
    source.last_status = "failure"
    source.last_error = error[:1024]


async def run_collection_for_source(db: AsyncSession, source: Source) -> CollectionRun:
    run = CollectionRun(source_id=source.id, status="success", started_at=_now())
    db.add(run)
    await db.flush()
    started = time.perf_counter()

    try:
        collector = get_collector(source.source_type)
        if collector is None:
            raise RuntimeError(f"no collector registered for {source.source_type}")

        run_id = run.id
        source_id = source.id
        # Clear any stale source-level cancel flag before we begin.
        try:
            await get_redis().delete(_cancel_source_key(source_id))
        except Exception:  # noqa: BLE001
            pass

        async def _should_cancel() -> bool:
            try:
                r = get_redis()
                run_flag = await r.get(_cancel_key(run_id))
                src_flag = await r.get(_cancel_source_key(source_id))
                return bool(run_flag or src_flag)
            except Exception:  # noqa: BLE001 — cancellation is best-effort
                return False

        result = await collector.collect(source, should_cancel=_should_cancel)
        latency = int((time.perf_counter() - started) * 1000)
        run.http_status = result.http_status
        run.latency_ms = latency
        run.items_discovered = result.discovered
        run.items_failed = result.failed

        if result.not_modified:
            _mark_success(source, latency, result)
        else:
            seen = new = dup = ver = 0
            for item in result.items:
                seen += 1
                ch = content_hash(item.raw_bytes)
                fp = fingerprint(item.text_for_fingerprint)
                existing = await _current_archive(
                    db, source.id, item.external_id, item.canonical_url
                )
                if existing is None:
                    row = await _insert_version(
                        db, source, item, ch, fp, version=1, supersedes=None,
                        http_status=result.http_status, ip=result.ip,
                    )
                    await _link_same_event(db, row)  # cross-source near-dup link
                    await _link_forwarded(db, row, item)  # forward provenance
                    new += 1
                elif existing.content_hash == ch or existing.fingerprint == fp:
                    dup += 1  # exact or semantically-identical => no new version
                else:
                    existing.is_current = False
                    row = await _insert_version(
                        db, source, item, ch, fp, version=existing.version + 1,
                        supersedes=existing.id, http_status=result.http_status, ip=result.ip,
                    )
                    ver += 1
            run.items_seen, run.items_new, run.items_duplicate, run.items_versioned = (
                seen, new, dup, ver,
            )
            _mark_success(source, latency, result)
        run.status = "cancelled" if result.cancelled else "success"
        log.info(
            "collection_ok", source=str(source.id), status=run.status,
            items_new=run.items_new, dup=run.items_duplicate, versioned=run.items_versioned,
        )
    except SSRFError as exc:
        _mark_failure(source, run, f"ssrf_blocked: {exc}")
        log.warning("collection_ssrf_blocked", source=str(source.id), error=str(exc))
    except Exception as exc:  # noqa: BLE001 — record any failure against the source
        _mark_failure(source, run, str(exc))
        log.warning("collection_failed", source=str(source.id), error=str(exc))
    finally:
        run.finished_at = _now()
        if run.latency_ms is None:
            run.latency_ms = int((time.perf_counter() - started) * 1000)
        await db.commit()
    return run


async def run_due_sources(db: AsyncSession, limit: int = 50) -> list[uuid.UUID]:
    """Return-and-run enabled sources whose interval has elapsed."""
    now = _now()
    res = await db.execute(select(Source).where(Source.enabled.is_(True)))
    ran: list[uuid.UUID] = []
    for source in res.scalars().all():
        due = (
            source.last_success_at is None
            or (now - source.last_success_at).total_seconds() >= source.collection_interval_seconds
        )
        if due:
            await run_collection_for_source(db, source)
            ran.append(source.id)
            if len(ran) >= limit:
                break
    return ran
