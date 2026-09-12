"""WEBSITE collector — a general public-web article collector.

Two modes (per source `extraction_config.mode`):
- "article" (default): the source URL is a single article page -> 1 item.
- "index": the source URL is a listing page -> discover same-host article links
  (bounded by max_articles), fetch and extract each.

Uses the SSRF-safe fetcher and the generic article extractor. No per-site code,
no external scraping services — collection runs from this server directly.
"""
from __future__ import annotations

import inspect

from app.core.logging import get_logger
from app.modules.collection.base import CollectedItem, Collector, CollectResult, register
from app.modules.collection.extraction import decode_html, discover_links, extract_article
from app.modules.collection.fetcher import fetch_with_retries

log = get_logger("web")

HTML_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
    "text/plain",
)


async def _should_stop(cb) -> bool:
    if cb is None:
        return False
    r = cb()
    if inspect.isawaitable(r):
        r = await r
    return bool(r)


def _item_from(
    html_bytes: bytes, content_type_header: str | None, url: str, config: dict
) -> CollectedItem:
    text, enc = decode_html(html_bytes, content_type_header)
    art = extract_article(text, url, config, encoding=enc)
    canonical = art.canonical_url or url
    extracted = {
        "title": art.title,
        "author": art.author,
        "body": art.body,
        "canonical_url": canonical,
        "language": art.language,
        "published_at": art.published_at.isoformat() if art.published_at else None,
        "updated_at": art.updated_at.isoformat() if art.updated_at else None,
        "images": art.images,
        "word_count": art.word_count,
        "encoding": art.encoding,
    }
    return CollectedItem(
        external_id=canonical,
        url=url,
        canonical_url=canonical,
        title=art.title,
        published_at=art.published_at,
        language=art.language,
        content_type="text/html",
        raw_bytes=html_bytes,  # original HTML preserved in the archive
        text_for_fingerprint=(art.body or art.title or ""),
        author=art.author,
        extracted=extracted,
    )


class WebsiteCollector(Collector):
    source_type = "WEBSITE"

    async def collect(self, source, should_cancel=None) -> CollectResult:
        config = source.extraction_config or {}
        mode = config.get("mode", "article")

        res = await fetch_with_retries(
            source.url, etag=source.etag, last_modified=source.last_modified,
            allowed_content_types=HTML_TYPES,
        )
        if res.not_modified:
            return CollectResult(http_status=304, not_modified=True, ip=res.ip)

        if mode == "article":
            item = _item_from(
                res.content, res.headers.get("content-type"), res.final_url or source.url, config
            )
            return CollectResult(
                items=[item], http_status=res.status, etag=res.headers.get("etag"),
                last_modified=res.headers.get("last-modified"), ip=res.ip, discovered=1,
            )

        # index mode: discover same-host article links, fetch + extract each.
        text, _ = decode_html(res.content, res.headers.get("content-type"))
        links = discover_links(text, res.final_url or source.url, config)
        items: list[CollectedItem] = []
        failed = 0
        cancelled = False
        for link in links:
            if await _should_stop(should_cancel):
                cancelled = True
                break
            try:
                sub = await fetch_with_retries(link, allowed_content_types=HTML_TYPES)
                if sub.not_modified:
                    continue
                items.append(
                    _item_from(
                        sub.content, sub.headers.get("content-type"), sub.final_url or link, config
                    )
                )
            except Exception as exc:  # noqa: BLE001 — one bad article must not fail the run
                failed += 1
                log.warning("article_fetch_failed", url=link, error=str(exc))

        return CollectResult(
            items=items, http_status=res.status, etag=res.headers.get("etag"),
            last_modified=res.headers.get("last-modified"), ip=res.ip,
            discovered=len(links), failed=failed, cancelled=cancelled,
        )


register(WebsiteCollector())
