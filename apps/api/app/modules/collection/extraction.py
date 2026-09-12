"""Generic article extraction — no hard-coded per-site selectors.

Strategy:
1. Structured metadata first: <meta> (OpenGraph/Twitter/Dublin Core), JSON-LD
   (schema.org NewsArticle/Article), <link rel=canonical>, <html lang>.
2. Generic body extraction via trafilatura (readability-style, works across sites).
3. Optional per-source overrides: if the source's `extraction_config` provides
   CSS selectors (title/body/author/date), they take precedence.

Encoding is detected from Content-Type, then a <meta charset>, then
charset-normalizer, before any parsing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import charset_normalizer
import trafilatura
from selectolax.parser import HTMLParser


@dataclass
class ExtractedArticle:
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None
    body: str = ""
    canonical_url: str | None = None
    language: str | None = None
    images: list[str] = field(default_factory=list)
    word_count: int = 0
    encoding: str | None = None


# --------------------------------------------------------------------------- #
def decode_html(content: bytes, content_type_header: str | None = None) -> tuple[str, str]:
    enc: str | None = None
    if content_type_header and "charset=" in content_type_header.lower():
        enc = content_type_header.lower().split("charset=")[-1].split(";")[0].strip() or None
    if not enc:
        head = content[:4096].decode("ascii", "ignore").lower()
        m = re.search(r'charset=["\']?([\w-]+)', head)
        if m:
            enc = m.group(1)
    if enc:
        try:
            return content.decode(enc, "replace"), enc
        except LookupError:
            pass
    best = charset_normalizer.from_bytes(content).best()
    if best is not None:
        return str(best), (best.encoding or "utf-8")
    return content.decode("utf-8", "replace"), "utf-8"


def _parse_dt(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        pass
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=UTC)
        except ValueError:
            return None
    return None


def _meta(tree: HTMLParser, *keys: str) -> str | None:
    for key in keys:
        for attr in ("property", "name", "itemprop"):
            node = tree.css_first(f'meta[{attr}="{key}"]')
            if node and node.attributes.get("content"):
                return node.attributes["content"].strip()
    return None


def _jsonld(tree: HTMLParser) -> dict:
    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text() or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            candidates = data.get("@graph", [data])
        else:
            candidates = []
        for item in candidates if isinstance(candidates, list) else [candidates]:
            if isinstance(item, dict) and "Article" in str(item.get("@type", "")):
                return item
    return {}


def _author_from(value) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return (value.get("name") or "").strip() or None
    if isinstance(value, list) and value:
        return _author_from(value[0])
    return None


def _selector_text(tree: HTMLParser, selector: str | None) -> str | None:
    if not selector:
        return None
    node = tree.css_first(selector)
    if not node:
        return None
    return (node.text() or "").strip() or None


def extract_article(
    html: str, url: str, config: dict | None = None, encoding: str | None = None
) -> ExtractedArticle:
    config = config or {}
    tree = HTMLParser(html)
    art = ExtractedArticle(encoding=encoding)

    ld = _jsonld(tree)

    # Title
    art.title = (
        _selector_text(tree, config.get("title_selector"))
        or _meta(tree, "og:title", "twitter:title")
        or (ld.get("headline") if isinstance(ld.get("headline"), str) else None)
        or _selector_text(tree, "h1")
    )
    # Author
    art.author = (
        _selector_text(tree, config.get("author_selector"))
        or _meta(tree, "author", "article:author", "dc.creator")
        or _author_from(ld.get("author"))
    )
    # Dates
    art.published_at = _parse_dt(
        _selector_text(tree, config.get("date_selector"))
        or _meta(tree, "article:published_time", "og:published_time", "dc.date")
        or ld.get("datePublished")
    )
    art.updated_at = _parse_dt(
        _meta(tree, "article:modified_time", "og:updated_time") or ld.get("dateModified")
    )
    # Canonical URL
    can = tree.css_first('link[rel="canonical"]')
    meop = ld.get("mainEntityOfPage")
    art.canonical_url = (
        (can.attributes.get("href") if can else None)
        or _meta(tree, "og:url")
        or (meop.get("@id") if isinstance(meop, dict) else None)
        or url
    )
    if art.canonical_url:
        art.canonical_url = urljoin(url, art.canonical_url)
    # Language
    html_node = tree.css_first("html")
    art.language = (
        (html_node.attributes.get("lang") if html_node else None)
        or _meta(tree, "og:locale", "dc.language")
    )
    if art.language:
        art.language = art.language.split("-")[0].split("_")[0][:16]
    # Images (public, canonical images only)
    imgs: list[str] = []
    for key in ("og:image", "twitter:image"):
        v = _meta(tree, key)
        if v:
            imgs.append(urljoin(url, v))
    ld_img = ld.get("image")
    if isinstance(ld_img, str):
        imgs.append(urljoin(url, ld_img))
    elif isinstance(ld_img, dict) and ld_img.get("url"):
        imgs.append(urljoin(url, ld_img["url"]))
    art.images = list(dict.fromkeys(imgs))

    # Body: configured selector wins, else generic trafilatura.
    body = _selector_text(tree, config.get("body_selector"))
    if not body:
        body = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    art.body = body.strip()
    art.word_count = len(art.body.split())

    return art


# --------------------------------------------------------------------------- #
def discover_links(html: str, base_url: str, config: dict | None = None) -> list[str]:
    """Discover candidate article links from an index page. Same-host only,
    bounded by max_articles. Uses config.link_selector when provided, else a
    conservative heuristic (anchors inside article/main/headline containers)."""
    config = config or {}
    tree = HTMLParser(html)
    base_host = (urlsplit(base_url).hostname or "").lower()
    selector = config.get("link_selector") or "article a, main a, h2 a, h3 a"
    max_articles = int(config.get("max_articles", 20))

    seen: list[str] = []
    for node in tree.css(selector):
        href = node.attributes.get("href")
        if not href:
            continue
        absolute = urljoin(base_url, href.strip())
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https"):
            continue
        if (parts.hostname or "").lower() != base_host:
            continue  # same-host only (no off-site crawling)
        clean = absolute.split("#")[0]
        if clean == base_url or clean in seen:
            continue
        seen.append(clean)
        if len(seen) >= max_articles:
            break
    return seen
