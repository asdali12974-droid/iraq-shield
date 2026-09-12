"""RSS / Atom collector — the first real collector.

Fetches the feed with the SSRF-safe fetcher (conditional GET supported), parses
it with feedparser, and yields one CollectedItem per entry. The raw bytes stored
per item are a stable JSON serialization of the entry as received (so the archive
faithfully preserves what was collected, independent of feedparser versions).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from time import mktime

import feedparser

from app.modules.collection.base import CollectedItem, Collector, CollectResult, register
from app.modules.collection.fetcher import fetch_with_retries


def _entry_datetime(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime.fromtimestamp(mktime(val), tz=UTC)
            except (OverflowError, ValueError):
                return None
    return None


def _entry_text(entry) -> str:
    parts = [entry.get("title", ""), entry.get("summary", "")]
    for c in entry.get("content", []) or []:
        parts.append(c.get("value", ""))
    return "\n".join(p for p in parts if p)


def _entry_external_id(entry) -> str | None:
    return entry.get("id") or entry.get("guid") or entry.get("link")


class RssCollector(Collector):
    source_type = "RSS"

    async def collect(self, source, should_cancel=None) -> CollectResult:
        res = await fetch_with_retries(
            source.url, etag=source.etag, last_modified=source.last_modified
        )
        if res.not_modified:
            return CollectResult(http_status=304, not_modified=True, ip=res.ip)

        parsed = feedparser.parse(res.content)
        items: list[CollectedItem] = []
        for entry in parsed.entries:
            ext_id = _entry_external_id(entry)
            if not ext_id:
                continue  # cannot dedup an entry with no stable id
            link = entry.get("link")
            raw_obj = {
                "id": ext_id,
                "title": entry.get("title"),
                "link": link,
                "summary": entry.get("summary"),
                "content": [c.get("value") for c in entry.get("content", []) or []],
                "published": entry.get("published") or entry.get("updated"),
                "author": entry.get("author"),
                "tags": [t.get("term") for t in entry.get("tags", []) or []],
            }
            raw_bytes = json.dumps(raw_obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
            items.append(
                CollectedItem(
                    external_id=ext_id,
                    url=link or source.url,
                    canonical_url=link,
                    title=entry.get("title"),
                    published_at=_entry_datetime(entry),
                    language=parsed.feed.get("language") or source.language,
                    content_type="application/json",
                    raw_bytes=raw_bytes,
                    text_for_fingerprint=_entry_text(entry),
                )
            )

        return CollectResult(
            items=items,
            http_status=res.status,
            etag=res.headers.get("etag"),
            last_modified=res.headers.get("last-modified"),
            ip=res.ip,
        )


register(RssCollector())
