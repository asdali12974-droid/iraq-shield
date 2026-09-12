"""TELEGRAM_PUBLIC_WEB collector.

Collects PUBLIC channel posts via HTTP from Telegram's public web preview at
``https://t.me/s/<username>``. No Telegram API, no MTProto, no api_id,
no api_hash, no session string, no Bot API, no user accounts.

Uses the existing SSRF-safe fetcher from P1.2. Reuses the raw archive,
deduplication, versioning, source health, RBAC, and audit infrastructure.

**Honest limitations (must be preserved):**
- The t.me/s/ page shows only a LIMITED WINDOW of recent posts — this collector
  does NOT claim to retrieve a channel's full history.
- ``post_id`` is extracted from ``data-post`` where available; if absent the post
  URL or a hash is used as the external_id — no fabricated message_id.
- ``published_at`` comes from the ``<time datetime>`` in the HTML; if absent it
  is ``None`` — no fabricated timestamp.
- Incremental collection uses ``last_cursor`` (highest post_id seen) to skip
  already-collected posts where possible.
- No proxies, no scraping services, no access to private content.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.modules.collection.base import CollectedItem, Collector, CollectResult, register
from app.modules.collection.fetcher import fetch_with_retries
from app.modules.collection.telegram_web.parser import parse_telegram_page

log = get_logger("telegram_web_collector")

HTML_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
)


def _username_of(source) -> str:
    """Extract the channel username from the source."""
    if source.telegram_username:
        return source.telegram_username.lstrip("@")
    # Derive from URL: https://t.me/s/<user> or https://t.me/<user>
    url = (source.url or "").rstrip("/")
    path = url.split("t.me/")[-1] if "t.me/" in url else ""
    # Strip /s/ prefix if present
    if path.startswith("s/"):
        path = path[2:]
    return path.lstrip("@")


def _build_url(username: str) -> str:
    """Build the t.me/s/ URL for a channel."""
    return f"https://t.me/s/{username}"


class TelegramWebCollector(Collector):
    """Collects Telegram public channel posts via HTTP (t.me/s/ pages)."""

    source_type = "TELEGRAM_PUBLIC_WEB"

    async def collect(self, source, should_cancel=None) -> CollectResult:
        username = _username_of(source)
        if not username:
            raise ValueError("no telegram username configured for this source")

        # Use the source's own URL when it already points at a /s/ page
        # (e.g. the test server), otherwise build the canonical URL.
        if source.url and "/s/" in source.url:
            page_url = source.url
        else:
            page_url = _build_url(username)

        # Fetch the page using the SSRF-safe fetcher (same as P1.2 WEBSITE)
        res = await fetch_with_retries(
            page_url,
            allowed_content_types=HTML_TYPES,
        )

        if res.not_modified:
            return CollectResult(http_status=304, not_modified=True, ip=res.ip)

        # Decode and parse the HTML
        html = res.content.decode("utf-8", errors="replace")
        parsed = parse_telegram_page(html, username)

        if not parsed.page_has_content:
            raise ValueError(
                f"t.me/s/{username} did not return a valid channel page"
            )

        # Update source metadata from the page (non-destructive: only set
        # title if we got one, preserve existing channel_id if any)
        if parsed.channel_title:
            source.telegram_title = parsed.channel_title
        source.telegram_username = username

        # Incremental: skip posts with post_id <= last_cursor
        min_id = int(source.last_cursor or "0") if source.last_cursor else 0

        items: list[CollectedItem] = []
        max_seen = min_id

        for post in parsed.posts:
            # Skip posts we've already collected (incremental)
            if post.post_id and post.post_id.isdigit():
                pid = int(post.post_id)
                if pid <= min_id:
                    continue
                max_seen = max(max_seen, pid)

            # Build the raw data structure — only provably available data
            raw = {
                "username": username,
                "post_id": post.post_id,
                "url": post.url,
                "text": post.text,
                "published_at": (
                    post.published_at.isoformat() if post.published_at else None
                ),
                "views": post.views,
                "author": post.author,
                "forwarded_from": post.forwarded_from,
                "forwarded_from_url": post.forwarded_from_url,
                "media_meta": post.media_meta,
                "collected_at": datetime.now(tz=UTC).isoformat(),
                "collection_method": "web_public_page",
            }

            extracted = {
                "text": post.text,
                "views": post.views,
                "media_meta": post.media_meta,
                "forward": (
                    {
                        "name": post.forwarded_from,
                        "url": post.forwarded_from_url,
                    }
                    if post.forwarded_from
                    else None
                ),
            }

            # External ID: use post_id if available, else URL hash for dedup
            external_id = (
                f"{username}:{post.post_id}"
                if post.post_id
                else f"{username}:hash:{post.content_hash[:16]}"
            )

            title = (
                (post.text or "").strip().splitlines()[0][:200]
                if post.text
                else None
            )

            raw_bytes = json.dumps(
                raw, ensure_ascii=False, sort_keys=True
            ).encode("utf-8")

            items.append(
                CollectedItem(
                    external_id=external_id,
                    url=post.url,
                    canonical_url=post.url,
                    title=title,
                    published_at=post.published_at,
                    language=source.language,
                    content_type="application/json",
                    raw_bytes=raw_bytes,
                    text_for_fingerprint=post.text or "",
                    author=post.author,
                    extracted=extracted,
                )
            )

        # Advance the incremental cursor
        if max_seen > min_id:
            source.last_cursor = str(max_seen)

        return CollectResult(
            items=items,
            http_status=res.status,
            ip=res.ip,
            discovered=len(parsed.posts),
        )


register(TelegramWebCollector())
