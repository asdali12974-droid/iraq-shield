"""Parse Telegram public channel pages (t.me/s/<username>).

This module extracts posts from the public HTML preview that Telegram serves at
``https://t.me/s/<username>``. It uses only data that is provably present in the
HTML — no Telegram API, no MTProto, no session credentials.

The page structure (as of 2026) renders each post inside a
``<div class="tgme_widget_message_wrap">`` containing:
  - ``data-post="<username>/<post_id>"`` on an inner div
  - ``.tgme_widget_message_text`` for the post body
  - ``.tgme_widget_message_date`` with a ``<time datetime="...">`` for the date
  - ``.tgme_widget_message_forwarded_from`` for forwarded posts
  - media preview elements (photo/video/document badges)
  - ``.tgme_widget_message_views`` for view counts

**Honesty constraints:**
- ``post_id`` is parsed from ``data-post`` (e.g. ``username/123`` → 123).
  If not available, we use the post URL hash as a fallback identifier.
- ``published_at`` comes from the ``<time datetime>`` element.
  If absent, it is ``None`` — we never fabricate a timestamp.
- The page shows only a LIMITED window of recent posts, NOT the full history.
  The caller must document this limitation honestly.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from selectolax.parser import HTMLParser


@dataclass
class TelegramPost:
    """A single post extracted from a t.me/s/ page."""

    post_id: str | None  # numeric id from data-post, or None if unavailable
    url: str  # full public URL (https://t.me/<user>/<id>)
    text: str | None  # post text body (may be None for media-only posts)
    published_at: datetime | None  # from <time datetime>, None if absent
    views: str | None  # view count string as displayed (e.g. "1.2K")
    author: str | None  # channel title / forwarded-from name
    forwarded_from: str | None  # original channel username if forwarded
    forwarded_from_url: str | None  # link to original post
    media_meta: dict | None = None  # type/description of attached media
    content_hash: str = ""  # SHA-256 of normalized text for dedup


@dataclass
class ParseResult:
    """Result of parsing a t.me/s/ page."""

    channel_title: str | None = None
    channel_username: str | None = None
    posts: list[TelegramPost] = field(default_factory=list)
    page_has_content: bool = False  # True if the page looks like a valid channel


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO datetime string from a <time> element."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _extract_post_id(data_post: str | None) -> tuple[str | None, str | None]:
    """Extract (username, post_id) from data-post='username/123'."""
    if not data_post:
        return None, None
    parts = data_post.rsplit("/", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], parts[1]
    return parts[0] if parts else None, None


def _extract_media_meta(msg_node) -> dict | None:
    """Extract media metadata from what is visible in the HTML."""
    media = {}

    # Photo
    photo = msg_node.css_first(".tgme_widget_message_photo_wrap")
    if photo:
        media["type"] = "photo"
        style = photo.attributes.get("style", "")
        bg_match = re.search(r"url\('([^']+)'\)", style)
        if bg_match:
            media["thumbnail_url"] = bg_match.group(1)
        return media

    # Video
    video = msg_node.css_first(".tgme_widget_message_video_wrap")
    if video:
        media["type"] = "video"
        thumb = video.css_first(".tgme_widget_message_video_thumb")
        if thumb:
            style = thumb.attributes.get("style", "")
            bg_match = re.search(r"url\('([^']+)'\)", style)
            if bg_match:
                media["thumbnail_url"] = bg_match.group(1)
        duration = msg_node.css_first(".message_video_duration")
        if duration:
            media["duration"] = (duration.text() or "").strip()
        return media

    # Document/file
    doc = msg_node.css_first(".tgme_widget_message_document_wrap")
    if doc:
        media["type"] = "document"
        title_el = doc.css_first(".tgme_widget_message_document_title")
        if title_el:
            media["filename"] = (title_el.text() or "").strip()
        extra_el = doc.css_first(".tgme_widget_message_document_extra")
        if extra_el:
            media["size"] = (extra_el.text() or "").strip()
        return media

    # Voice/round video
    voice = msg_node.css_first(".tgme_widget_message_voice")
    if voice:
        media["type"] = "voice"
        return media

    # Sticker
    sticker = msg_node.css_first(".tgme_widget_message_sticker_wrap")
    if sticker:
        media["type"] = "sticker"
        return media

    # Poll
    poll = msg_node.css_first(".tgme_widget_message_poll")
    if poll:
        media["type"] = "poll"
        question = poll.css_first(".tgme_widget_message_poll_question")
        if question:
            media["question"] = (question.text() or "").strip()
        return media

    return None if not media else media


def _text_hash(text: str | None, media_meta: dict | None = None) -> str:
    """SHA-256 of normalized text (+ media type when text is empty) for dedup.

    When text is absent (media-only posts), include the media type so that
    two different media-only posts don't collide on the hash of an empty string.
    """
    normalized = (text or "").strip()
    if not normalized and media_meta:
        # Include media type to differentiate media-only posts
        normalized = f"__media__{media_meta.get('type', 'unknown')}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_telegram_page(html: str, username: str) -> ParseResult:
    """Parse a t.me/s/<username> HTML page and extract all visible posts.

    Args:
        html: the full HTML content of the page
        username: the channel username (used for URL construction)

    Returns:
        ParseResult with channel info and list of posts
    """
    tree = HTMLParser(html)
    result = ParseResult()

    # Extract channel title from the page header
    title_node = tree.css_first(".tgme_channel_info_header_title")
    if title_node:
        result.channel_title = (title_node.text() or "").strip() or None
        result.channel_username = username
        result.page_has_content = True

    # Also check for the page-level channel name in the widget header
    if not result.channel_title:
        header = tree.css_first(".tgme_header_title")
        if header:
            result.channel_title = (header.text() or "").strip() or None

    # Detect valid channel page even without title
    if tree.css_first(".tgme_widget_message_wrap"):
        result.page_has_content = True

    # Extract each post
    for wrap in tree.css(".tgme_widget_message_wrap"):
        msg = wrap.css_first(".tgme_widget_message")
        if not msg:
            continue

        # data-post attribute: "username/post_id"
        data_post = msg.attributes.get("data-post")
        _, post_id = _extract_post_id(data_post)

        # Build URL from post_id if available
        if post_id:
            url = f"https://t.me/{username}/{post_id}"
        elif data_post:
            url = f"https://t.me/{data_post}"
        else:
            # No data-post at all — use a hash-based fallback
            url = f"https://t.me/{username}"

        # Post text
        text_node = msg.css_first(".tgme_widget_message_text")
        text = (text_node.text() or "").strip() if text_node else None

        # Published timestamp
        time_node = msg.css_first("time")
        published_at = _parse_datetime(
            time_node.attributes.get("datetime") if time_node else None
        )

        # Views
        views_node = msg.css_first(".tgme_widget_message_views")
        views = (views_node.text() or "").strip() if views_node else None

        # Author (channel name on the post)
        author_node = msg.css_first(".tgme_widget_message_owner_name")
        author = (author_node.text() or "").strip() if author_node else None

        # Forwarded-from
        fwd_node = msg.css_first(".tgme_widget_message_forwarded_from_name")
        forwarded_from = None
        forwarded_from_url = None
        if fwd_node:
            forwarded_from = (fwd_node.text() or "").strip() or None
            fwd_link = fwd_node.css_first("a")
            if fwd_link:
                forwarded_from_url = fwd_link.attributes.get("href")
                forwarded_from = (fwd_link.text() or "").strip() or forwarded_from

        # Media
        media_meta = _extract_media_meta(msg)

        post = TelegramPost(
            post_id=post_id,
            url=url,
            text=text if text else None,
            published_at=published_at,
            views=views,
            author=author,
            forwarded_from=forwarded_from,
            forwarded_from_url=forwarded_from_url,
            media_meta=media_meta,
            content_hash=_text_hash(text, media_meta),
        )
        result.posts.append(post)

    return result
