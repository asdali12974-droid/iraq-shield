"""Channel verification: resolve a public @username to its real channel_id/title.

Only sets verification_status='verified' after a REAL successful resolve. When
Telegram is not configured/reachable, it leaves the source as 'pending' and says
so — it never fabricates a verification result.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.collection import Source
from app.modules.collection.telegram.client import get_telegram_client
from app.modules.collection.telegram.collector import _username_of

log = get_logger("telegram_verify")


async def verify_source(db: AsyncSession, source: Source) -> dict:
    if source.source_type != "TELEGRAM_PUBLIC":
        return {"status": source.verification_status, "reason": "not a telegram source"}

    client = get_telegram_client()
    if client is None:
        # No connectivity/credentials — do NOT claim verification.
        source.verification_status = "pending"
        await db.commit()
        return {"status": "pending", "reason": "telegram_not_configured"}

    try:
        await client.connect()
        ch = await client.resolve_channel(_username_of(source))
        source.telegram_channel_id = ch.channel_id
        source.telegram_title = ch.title
        source.telegram_username = ch.username
        source.verification_status = "verified"
        source.verified_at = datetime.now(tz=UTC)
        await db.commit()
        log.info("telegram_verified", source=str(source.id), channel_id=ch.channel_id)
        return {
            "status": "verified",
            "channel_id": ch.channel_id,
            "title": ch.title,
            "username": ch.username,
            "public_url": f"https://t.me/{ch.username}",
        }
    except Exception as exc:  # noqa: BLE001
        source.verification_status = "failed"
        source.last_error = str(exc)[:1024]
        await db.commit()
        return {"status": "failed", "reason": str(exc)[:200]}
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
