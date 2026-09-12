"""Test fixture: generate realistic t.me/s/<username> HTML pages.

These are LOCAL test pages that mimic the PUBLIC structure of Telegram's web
preview. They contain NO real Telegram data — only test content for validating
the parser and collector. No Telegram API is used.

The HTML structure is based on the public t.me/s/ page format:
- Channel info header with title
- Message widgets with data-post, text, datetime, views, media, forwards
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakePost:
    post_id: int | None  # None → no data-post attribute in HTML
    text: str | None = None
    datetime: str | None = "2026-08-29T10:00:00+00:00"  # None → no <time> element
    views: str | None = "1.2K"  # None → no views element
    author: str | None = None
    forwarded_from: str | None = None
    forwarded_from_url: str | None = None
    media_type: str | None = None  # photo, video, document, etc.
    media_extra: dict | None = None


def make_telegram_page(
    username: str,
    title: str,
    posts: list[FakePost] | None = None,
    *,
    include_header: bool = True,
    valid_channel: bool = True,
) -> str:
    """Build a realistic t.me/s/ HTML page for testing.

    Args:
        username: channel username
        title: channel display title
        posts: list of FakePost objects to include
        include_header: whether to include the channel info header
        valid_channel: if False, return an empty/invalid page
    """
    if not valid_channel:
        return """<!DOCTYPE html>
<html><head><title>Telegram</title></head>
<body><div class="tgme_page_wrap">
  <div class="tgme_body_wrap">Page not found</div>
</div></body></html>"""

    posts = posts or []
    post_html_parts = []

    for post in posts:
        text_html = ""
        if post.text:
            text_html = f"""
            <div class="tgme_widget_message_text js-message_text"
                 dir="auto">{post.text}</div>"""

        views_html = ""
        if post.views:
            views_html = f"""
            <span class="tgme_widget_message_views">{post.views}</span>"""

        time_html = ""
        if post.datetime is not None:
            pid_for_link = post.post_id if post.post_id is not None else "0"
            time_html = f"""
            <a class="tgme_widget_message_date"
               href="https://t.me/{username}/{pid_for_link}">
              <time datetime="{post.datetime}"
                    class="time">{post.datetime[:10]}</time>
            </a>"""

        author_html = ""
        if post.author:
            author_html = f"""
            <a class="tgme_widget_message_owner_name"
               href="https://t.me/{username}">{post.author}</a>"""

        fwd_html = ""
        if post.forwarded_from:
            fwd_url = post.forwarded_from_url or "#"
            fwd_html = f"""
            <div class="tgme_widget_message_forwarded_from">
              Forwarded from
              <a class="tgme_widget_message_forwarded_from_name"
                 href="{fwd_url}">{post.forwarded_from}</a>
            </div>"""

        media_html = ""
        if post.media_type == "photo":
            thumb = (post.media_extra or {}).get("thumbnail_url", "")
            media_html = f"""
            <a class="tgme_widget_message_photo_wrap"
               style="background-image:url('{thumb}')"></a>"""
        elif post.media_type == "video":
            duration = (post.media_extra or {}).get("duration", "0:30")
            media_html = f"""
            <div class="tgme_widget_message_video_wrap">
              <div class="tgme_widget_message_video_thumb"></div>
              <span class="message_video_duration">{duration}</span>
            </div>"""
        elif post.media_type == "document":
            filename = (post.media_extra or {}).get("filename", "file.pdf")
            size = (post.media_extra or {}).get("size", "1.2 MB")
            media_html = f"""
            <div class="tgme_widget_message_document_wrap">
              <div class="tgme_widget_message_document_title">{filename}</div>
              <div class="tgme_widget_message_document_extra">{size}</div>
            </div>"""
        elif post.media_type == "poll":
            question = (post.media_extra or {}).get("question", "سؤال؟")
            media_html = f"""
            <div class="tgme_widget_message_poll">
              <div class="tgme_widget_message_poll_question">{question}</div>
            </div>"""

        data_post_attr = ""
        if post.post_id is not None:
            data_post_attr = f' data-post="{username}/{post.post_id}"'

        post_html = f"""
    <div class="tgme_widget_message_wrap js-widget_message_wrap">
      <div class="tgme_widget_message text_not_supported_wrap js-widget_message"
          {data_post_attr}>
        <div class="tgme_widget_message_bubble">
          {author_html}
          {fwd_html}
          {media_html}
          {text_html}
          <div class="tgme_widget_message_info short js-message_info">
            {views_html}
            {time_html}
          </div>
        </div>
      </div>
    </div>"""
        post_html_parts.append(post_html)

    header_html = ""
    if include_header:
        header_html = f"""
    <div class="tgme_channel_info">
      <div class="tgme_channel_info_header">
        <div class="tgme_channel_info_header_title" dir="auto">
          <span>{title}</span>
        </div>
      </div>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="ar">
<head>
  <meta charset="UTF-8">
  <title>Telegram: Contact @{username}</title>
</head>
<body>
  <div class="tgme_page_wrap">
    {header_html}
    <div class="tgme_body_wrap">
      <section class="tgme_channel_history js-message_history">
        {''.join(post_html_parts)}
      </section>
    </div>
  </div>
</body>
</html>"""
