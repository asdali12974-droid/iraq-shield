"""HTTP-based channel verification for TELEGRAM_PUBLIC_WEB sources.

Verifies a channel by fetching its public page at ``https://t.me/s/<username>``
and checking that it returns valid channel content. Extracts the channel title
from the HTML. No Telegram API — verification is purely HTTP-based.

Sets ``verification_status='verified'`` ONLY after a real successful HTTP fetch
that returns recognisable channel content. Never fabricates verification results.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.collection import Source
from app.modules.collection.fetcher import FetchError, fetch_with_retries
from app.modules.collection.telegram_web.parser import parse_telegram_page

log = get_logger("telegram_web_verify")

HTML_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
)


def _username_of(source: Source) -> str:
    if source.telegram_username:
        return source.telegram_username.lstrip("@")
    url = (source.url or "").rstrip("/")
    path = url.split("t.me/")[-1] if "t.me/" in url else ""
    if path.startswith("s/"):
        path = path[2:]
    return path.lstrip("@")


async def verify_source(db: AsyncSession, source: Source) -> dict:
    """Verify a Telegram source by HTTP-fetching its public page.

    Returns a dict describing the verification result. Updates the source
    row in the database.
    """
    if source.source_type not in ("TELEGRAM_PUBLIC", "TELEGRAM_PUBLIC_WEB"):
        return {"status": source.verification_status, "reason": "not a telegram source"}

    username = _username_of(source)
    if not username:
        source.verification_status = "failed"
        source.last_error = "no telegram username configured"
        await db.commit()
        return {"status": "failed", "reason": "no telegram username configured"}

    page_url = f"https://t.me/s/{username}"

    try:
        res = await fetch_with_retries(
            page_url,
            allowed_content_types=HTML_TYPES,
        )

        html = res.content.decode("utf-8", errors="replace")
        parsed = parse_telegram_page(html, username)

        if not parsed.page_has_content:
            source.verification_status = "failed"
            source.last_error = f"page at {page_url} has no channel content"
            await db.commit()
            return {
                "status": "failed",
                "reason": f"page at {page_url} does not contain channel content",
            }

        # Successful verification
        source.telegram_username = username
        if parsed.channel_title:
            source.telegram_title = parsed.channel_title
        source.verification_status = "verified"
        source.verified_at = datetime.now(tz=UTC)
        source.last_error = None
        await db.commit()

        log.info(
            "telegram_web_verified",
            source=str(source.id),
            username=username,
            title=parsed.channel_title,
        )
        return {
            "status": "verified",
            "title": parsed.channel_title,
            "username": username,
            "public_url": page_url,
            "posts_visible": len(parsed.posts),
        }

    except FetchError as exc:
        source.verification_status = "failed"
        source.last_error = str(exc)[:1024]
        await db.commit()
        log.warning(
            "telegram_web_verify_failed",
            source=str(source.id),
            username=username,
            error=str(exc),
        )
        return {"status": "failed", "reason": str(exc)[:200]}

    except Exception as exc:  # noqa: BLE001
        source.verification_status = "failed"
        source.last_error = str(exc)[:1024]
        await db.commit()
        return {"status": "failed", "reason": str(exc)[:200]}
