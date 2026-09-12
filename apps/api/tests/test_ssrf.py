"""SSRF guard unit tests — no external network required."""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.core.ssrf import SSRFError, validate_url

BLOCKED = [
    "http://localhost/feed",
    "http://127.0.0.1/",
    "http://127.0.0.1:6379/",  # would hit Redis
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://metadata.google.internal/",
    "http://10.0.0.5/",
    "http://192.168.1.10/",
    "http://172.16.0.1/",
    "http://[::1]/",
    "http://0.0.0.0/",
    "http://[::ffff:127.0.0.1]/",  # IPv4-mapped loopback
]

BAD_SCHEME = ["ftp://example.com/", "file:///etc/passwd", "gopher://x/", "http:///nohost"]


@pytest.mark.parametrize("url", BLOCKED)
def test_blocks_internal_targets(url):
    with pytest.raises(SSRFError):
        validate_url(url)


@pytest.mark.parametrize("url", BAD_SCHEME)
def test_rejects_bad_schemes_or_missing_host(url):
    with pytest.raises(SSRFError):
        validate_url(url)


def test_allows_public_ip_literal():
    # A public IP literal is allowed (no DNS needed): 93.184.216.34 (example.com).
    t = validate_url("http://93.184.216.34/feed.xml")
    assert t.host == "93.184.216.34"


def test_allow_private_flag_lifts_block(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "collector_allow_private_hosts", True)
    # In local/test mode a loopback target is permitted (fake feed server).
    t = validate_url("http://127.0.0.1:8099/feed.xml")
    assert t.host == "127.0.0.1"
