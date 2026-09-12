"""A tiny real HTTP server used by collection tests.

It serves actual RSS/Atom bytes over HTTP on 127.0.0.1 so the collector performs
a genuine fetch + parse + archive. Nothing is injected into the database — data
only ever enters through the real collection path. The server is mutable so tests
can change a feed (versioning), fail transiently (retries), stall (timeout), or
disallow via robots.txt.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Route:
    body: bytes = b""
    content_type: str = "application/rss+xml"
    status: int = 200
    fail_times: int = 0  # return 503 this many times before succeeding
    delay: float = 0.0  # seconds to stall (timeout testing)


@dataclass
class FeedServer:
    routes: dict[str, Route] = field(default_factory=dict)
    _httpd: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None
    port: int = 0

    def set(self, path: str, body: bytes | str, content_type: str = "application/rss+xml", **kw):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.routes[path] = Route(body=body, content_type=content_type, **kw)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def do_GET(self):
                route = server.routes.get(self.path)
                if route is None:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"not found")
                    return
                if route.delay:
                    time.sleep(route.delay)
                if route.fail_times > 0:
                    route.fail_times -= 1
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(b"try later")
                    return
                self.send_response(route.status)
                self.send_header("Content-Type", route.content_type)
                self.send_header("Content-Length", str(len(route.body)))
                self.end_headers()
                self.wfile.write(route.body)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()


def make_rss(items: list[dict], title: str = "Test Feed") -> str:
    """Build a real RSS 2.0 document. `items` are illustrative — they enter the
    system only via a real HTTP fetch + parse, never by direct DB insert."""
    entries = []
    for it in items:
        entries.append(
            f"""<item>
      <title>{it['title']}</title>
      <link>{it['link']}</link>
      <guid isPermaLink="false">{it['guid']}</guid>
      <pubDate>{it.get('pubDate', 'Wed, 01 Jan 2026 10:00:00 +0000')}</pubDate>
      <description>{it['description']}</description>
    </item>"""
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>{title}</title>
  <link>http://127.0.0.1/</link>
  <language>ar</language>
  {''.join(entries)}
</channel></rss>"""
