"""Hashing & fingerprinting for deduplication and change detection.

- content_hash: SHA-256 of the exact raw bytes (exact-duplicate detection).
- fingerprint:  SHA-256 of normalized text (HTML stripped, lowercased, whitespace
  collapsed) — detects a *real* content change vs. a trivial byte difference.
"""
from __future__ import annotations

import hashlib
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_text(text: str) -> str:
    text = _TAG_RE.sub(" ", text)
    text = text.replace("&nbsp;", " ")
    text = _WS_RE.sub(" ", text)
    return text.strip().lower()


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
