"""Data-sovereignty guard: the frontend must make no third-party requests.

Scans the app's own source (never node_modules/dist) for external hosts. This
prevents a regression where a font CDN, analytics snippet, or other external
call is reintroduced into a platform that must run fully self-hosted / air-gapped.
"""
from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "apps" / "web"
SCAN_ROOTS = [WEB / "index.html", WEB / "src"]
EXTS = {".html", ".css", ".ts", ".tsx", ".js"}

FORBIDDEN = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "googletagmanager",
    "google-analytics",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "cdnjs.cloudflare.com",
)


def _source_files():
    for root in SCAN_ROOTS:
        if root.is_file():
            yield root
        elif root.is_dir():
            for p in root.rglob("*"):
                if p.is_file() and p.suffix in EXTS:
                    yield p


def test_frontend_has_no_external_hosts():
    offenders = []
    for f in _source_files():
        text = f.read_text(errors="ignore")
        for host in FORBIDDEN:
            if host in text:
                offenders.append(f"{f.name}: {host}")
    assert not offenders, f"external hosts found in frontend: {offenders}"
