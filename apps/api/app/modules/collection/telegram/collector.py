"""TELEGRAM_PUBLIC collector.

Collects PUBLIC channel posts via the official MTProto client (the port). Handles
initial + incremental collection (cursor = last message_id), pagination limit,
flood-wait (sleep within threshold, else fail), and graceful reconnect. Resolves
the channel on each run and records the real channel_id/title/verification.

No private data, no personal-data harvesting, no media downloads (metadata only).
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.collection.base import CollectedItem, Collector, CollectResult, register
from app.modules.collection.telegram.client import get_telegram_client
from app.modules.collection.telegram.port import (
    FloodWait,
    TelegramError,
    TelegramNotConfigured,
    TgChannel,
)

log = get_logger("telegram_collector")


def _username_of(source) -> str:
    if source.telegram_username:
        return source.telegram_username.lstrip("@")
    # Derive from a t.me URL if needed.
    url = (source.url or "").rstrip("/")
    return url.split("/")[-1].lstrip("@")


async def _connect_with_retry(client) -> None:
    try:
        await client.connect()
    except TelegramError:
        await asyncio.sleep(0.2)  # graceful reconnect: one retry
        await client.connect()


class TelegramCollector(Collector):
    source_type = "TELEGRAM_PUBLIC"

    async def collect(self, source, should_cancel=None) -> CollectResult:
        s = get_settings()
        client = get_telegram_client()
        if client is None:
            # No credentials -> clean failure, never fabricated data.
            raise TelegramNotConfigured("Telegram credentials not configured")

        await _connect_with_retry(client)
        try:
            channel = await client.resolve_channel(_username_of(source))
            # Record the verified channel identity on the source.
            source.telegram_channel_id = channel.channel_id
            source.telegram_title = channel.title
            source.telegram_username = channel.username
            source.verification_status = "verified"
            source.verified_at = datetime.now(tz=UTC)

            min_id = int(source.last_cursor or 0)
            messages = await self._fetch(client, channel, min_id, s)

            items: list[CollectedItem] = []
            max_seen = min_id
            for m in messages:
                max_seen = max(max_seen, m.message_id)
                public_url = f"https://t.me/{channel.username}/{m.message_id}"
                raw = {
                    "channel_id": channel.channel_id,
                    "username": channel.username,
                    "message_id": m.message_id,
                    "date": m.date.isoformat(),
                    "edit_date": m.edit_date.isoformat() if m.edit_date else None,
                    "text": m.text,
                    "views": m.views,
                    "fwd_from_channel_id": m.fwd_from_channel_id,
                    "fwd_from_username": m.fwd_from_username,
                    "fwd_from_message_id": m.fwd_from_message_id,
                    "media_meta": m.media_meta,
                }
                extracted = {
                    "text": m.text,
                    "views": m.views,
                    "edit_date": raw["edit_date"],
                    "media_meta": m.media_meta,
                    "forward": (
                        {
                            "channel_id": m.fwd_from_channel_id,
                            "username": m.fwd_from_username,
                            "message_id": m.fwd_from_message_id,
                        }
                        if (m.fwd_from_channel_id or m.fwd_from_username)
                        else None
                    ),
                }
                title = (m.text or "").strip().splitlines()[0][:200] if m.text else None
                raw_bytes = json.dumps(
                    raw, ensure_ascii=False, sort_keys=True
                ).encode("utf-8")
                items.append(
                    CollectedItem(
                        external_id=f"{channel.channel_id}:{m.message_id}",
                        url=public_url,
                        canonical_url=public_url,
                        title=title,
                        published_at=m.date,
                        language=source.language,
                        content_type="application/json",
                        raw_bytes=raw_bytes,
                        text_for_fingerprint=m.text or "",
                        extracted=extracted,
                    )
                )

            # Advance the incremental cursor.
            if max_seen > min_id:
                source.last_cursor = str(max_seen)

            return CollectResult(items=items, http_status=None, discovered=len(items))
        finally:
            await client.disconnect()

    async def _fetch(self, client, channel: TgChannel, min_id: int, s):
        try:
            return await client.fetch_messages(
                channel, min_id=min_id, limit=s.telegram_max_messages_per_run
            )
        except FloodWait as fw:
            if fw.seconds <= s.telegram_flood_sleep_threshold:
                log.warning("telegram_flood_wait", seconds=fw.seconds)
                await asyncio.sleep(fw.seconds)
                return await client.fetch_messages(
                    channel, min_id=min_id, limit=s.telegram_max_messages_per_run
                )
            raise TelegramError(f"flood_wait {fw.seconds}s exceeds threshold") from fw


register(TelegramCollector())
