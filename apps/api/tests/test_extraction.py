"""Article extraction tests — real HTML parsed by the real extractor.

These HTML strings are inputs to the genuine extraction pipeline (like a fixture
fed to a parser), not application data inserted into the system."""
from __future__ import annotations

from app.modules.collection.extraction import (
    decode_html,
    discover_links,
    extract_article,
)

ARTICLE_HTML = """<!doctype html><html lang="ar-IQ"><head>
<meta charset="utf-8">
<meta property="og:title" content="عنوان الخبر من OpenGraph">
<meta property="article:published_time" content="2026-08-29T10:00:00+00:00">
<meta property="article:modified_time" content="2026-08-29T12:30:00+00:00">
<meta name="author" content="محرر الاختبار">
<meta property="og:image" content="/media/photo.jpg">
<link rel="canonical" href="https://news.example.test/story/42">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"NewsArticle","headline":"عنوان JSON-LD",
 "datePublished":"2026-08-29T10:00:00Z","author":{"@type":"Person","name":"كاتب JSONLD"}}
</script>
</head><body>
<nav>روابط تنقّل لا يجب أن تدخل المتن</nav>
<article><h1>عنوان الخبر من OpenGraph</h1>
<p>هذه فقرة أولى من متن الخبر تتضمّن تفاصيل كافية حتى تُعتبر مقالاً حقيقياً وليست عنصر واجهة.</p>
<p>وهذه فقرة ثانية تضيف مزيداً من السياق حول الحدث المفترض في هذا الاختبار المحلي المطوّل.</p>
</article></body></html>"""


def test_extract_full_article():
    art = extract_article(ARTICLE_HTML, "https://news.example.test/story/42?utm=x")
    assert art.title == "عنوان الخبر من OpenGraph"
    assert art.author == "محرر الاختبار"
    assert art.published_at is not None and art.published_at.year == 2026
    assert art.updated_at is not None and art.updated_at.hour == 12
    assert art.canonical_url == "https://news.example.test/story/42"
    assert art.language == "ar"
    assert art.images and art.images[0].endswith("/media/photo.jpg")
    assert "فقرة أولى" in art.body
    assert "تنقّل" not in art.body  # nav stripped by generic extraction
    assert art.word_count > 5


def test_configured_selectors_override():
    html = "<html><body><h2 class='t'>عنوان مخصّص</h2><div class='b'>متن مخصّص كافٍ للطول</div></body></html>"
    cfg = {"title_selector": "h2.t", "body_selector": "div.b"}
    art = extract_article(html, "https://x.test/a", config=cfg)
    assert art.title == "عنوان مخصّص"
    assert "متن مخصّص" in art.body


def test_malformed_html_does_not_crash():
    html = "<html><head><title>ناقص<body><p>فقرة بلا إغلاق <div><span>عناصر متداخلة"
    art = extract_article(html, "https://x.test/b")
    assert isinstance(art.body, str)  # no exception; best-effort


def test_encoding_detection_windows1256():
    text = "مرحبا بالعالم من بغداد"
    html = f'<html><head><meta charset="windows-1256"></head><body><p>{text}</p></body></html>'
    raw = html.encode("windows-1256")
    decoded, enc = decode_html(raw, None)
    assert "مرحبا" in decoded
    assert enc.lower() in ("windows-1256", "cp1256")


def test_encoding_from_content_type_header():
    raw = "<html><body><p>نصّ عربي</p></body></html>".encode()
    decoded, enc = decode_html(raw, "text/html; charset=utf-8")
    assert "عربي" in decoded and enc == "utf-8"


def test_discover_links_same_host_only():
    html = """<html><body><main>
      <h2><a href="/news/1">خبر ١</a></h2>
      <h2><a href="https://site.test/news/2">خبر ٢</a></h2>
      <h2><a href="https://evil.test/x">خارجي</a></h2>
      <a href="/about">عن</a>
    </main></body></html>"""
    links = discover_links(html, "https://site.test/", {"max_articles": 10})
    assert "https://site.test/news/1" in links
    assert "https://site.test/news/2" in links
    assert all("evil.test" not in u for u in links)  # off-site excluded


def test_discover_links_respects_max():
    items = "".join(f'<h3><a href="/n/{i}">x</a></h3>' for i in range(30))
    html = f"<html><body><main>{items}</main></body></html>"
    links = discover_links(html, "https://s.test/", {"max_articles": 5})
    assert len(links) == 5
