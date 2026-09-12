"""SSRF-safe, polite HTTP fetcher used by all collectors.

Enforces: scheme + IP validation (SSRF), per-host rate limiting, robots.txt,
a clear User-Agent, conditional GET (ETag/Last-Modified), bounded redirects
(each hop re-validated), request timeout, response size cap, and a content-type
allowlist. Retries/backoff are applied by `fetch_with_retries`.
"""
from __future__ import annotations

import asyncio
import ssl
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpcore
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.ssrf import SSRFError, validate_url

log = get_logger("fetcher")

DEFAULT_ALLOWED_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
    "application/rdf+xml",
    "text/html",
    "application/xhtml+xml",
    "text/plain",
)


REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})  # NOT 304 (Not Modified)


class FetchError(Exception):
    """Any non-SSRF fetch failure (timeout, too big, bad type, robots, HTTP error)."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    content: bytes
    content_type: str | None
    ip: str | None
    not_modified: bool = False
    elapsed_ms: int = 0
    meta: dict = field(default_factory=dict)


# --- per-host politeness rate limit (Redis min-interval) ---
async def _respect_rate_limit(host: str) -> None:
    s = get_settings()
    interval = s.collector_min_host_interval_seconds
    if interval <= 0:
        return
    key = f"rl:host:{host}"
    try:
        r = get_redis()
        for _ in range(3):
            ok = await r.set(key, "1", nx=True, px=int(interval * 1000))
            if ok:
                return
            ttl = await r.pttl(key)
            await asyncio.sleep(max(ttl, 50) / 1000.0)
    except Exception as exc:  # noqa: BLE001 — politeness must not hard-fail
        log.warning("rate_limit_unavailable", host=host, error=str(exc))


# --- robots.txt (cached per host) ---
_robots_cache: dict[str, RobotFileParser | None] = {}


async def _robots_allows(url: str, user_agent: str) -> bool:
    parts = urlsplit(url)
    host_key = f"{parts.scheme}://{parts.netloc}"
    if host_key not in _robots_cache:
        robots_url = f"{host_key}/robots.txt"
        rp: RobotFileParser | None = RobotFileParser()
        try:
            res = await _raw_get(robots_url, headers={"User-Agent": user_agent}, max_bytes=512_000)
            if res.status == 200:
                rp.parse(res.content.decode("utf-8", errors="ignore").splitlines())
            else:
                rp = None  # no usable robots => allow
        except (FetchError, SSRFError, Exception):  # noqa: BLE001
            rp = None
        _robots_cache[host_key] = rp
    rp = _robots_cache[host_key]
    if rp is None:
        return True
    return rp.can_fetch(user_agent, url)


async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    chunks = bytearray()
    async for chunk in response.aiter_bytes():
        chunks.extend(chunk)
        if len(chunks) > max_bytes:
            raise FetchError(f"response exceeds max size ({max_bytes} bytes)")
    return bytes(chunks)


class _PinnedBackend(httpcore.AnyIOBackend):
    """Forces the TCP connection to a pre-validated IP while TLS/SNI/Host still
    use the original hostname. This closes the DNS-rebinding window: even if DNS
    changes after validation, we only ever dial the IP we already vetted."""

    def __init__(self, ip: str) -> None:
        self._ip = ip

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return await super().connect_tcp(
            self._ip, port, timeout=timeout,
            local_address=local_address, socket_options=socket_options,
        )


def _build_client(pin_ip: str | None, timeout: float) -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(verify=True, retries=0)
    if pin_ip:
        # Rebuild the pool so connections go to the validated IP (cert still
        # verified against the hostname via a standard verifying SSL context).
        transport._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=_PinnedBackend(pin_ip),
        )
    return httpx.AsyncClient(transport=transport, follow_redirects=False, timeout=timeout)


async def _raw_get(
    url: str,
    *,
    headers: dict[str, str],
    max_bytes: int,
    timeout: float | None = None,
    max_redirects: int = 0,
) -> FetchResult:
    """Single guarded GET with manual, re-validated + IP-pinned redirects."""
    s = get_settings()
    timeout = timeout or s.collector_timeout_seconds
    started = time.perf_counter()
    current = url
    redirects = 0

    while True:
        target = validate_url(current)  # SSRF: raises on private/blocked
        pin_ip = target.ips[0] if target.ips else None
        client = _build_client(pin_ip, timeout)
        try:
            async with client.stream("GET", current, headers=headers) as resp:
                # NB: httpx treats 304 as is_redirect; handle real redirects only.
                if resp.status_code in REDIRECT_CODES and redirects < max_redirects:
                    loc = resp.headers.get("location")
                    if not loc:
                        raise FetchError("redirect without Location")
                    current = urljoin(current, loc)
                    redirects += 1
                    continue  # next hop: re-validate + re-pin
                content = b"" if resp.status_code == 304 else await _read_capped(resp, max_bytes)
                elapsed = int((time.perf_counter() - started) * 1000)
                return FetchResult(
                    url=url,
                    final_url=str(resp.url),
                    status=resp.status_code,
                    headers={k.lower(): v for k, v in resp.headers.items()},
                    content=content,
                    content_type=resp.headers.get("content-type", "").split(";")[0].strip() or None,
                    ip=pin_ip,
                    not_modified=(resp.status_code == 304),
                    elapsed_ms=elapsed,
                )
        finally:
            await client.aclose()


async def fetch(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    allowed_content_types: tuple[str, ...] = DEFAULT_ALLOWED_TYPES,
) -> FetchResult:
    """Polite, SSRF-safe fetch with robots, rate limit, conditional GET, caps."""
    s = get_settings()
    validate_url(url)  # fail fast on SSRF before any network work
    host = urlsplit(url).hostname or ""

    if s.collector_respect_robots and not await _robots_allows(url, s.collector_user_agent):
        raise FetchError("blocked by robots.txt")

    await _respect_rate_limit(host)

    headers = {"User-Agent": s.collector_user_agent, "Accept": ", ".join(allowed_content_types)}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    result = await _raw_get(
        url,
        headers=headers,
        max_bytes=s.collector_max_bytes,
        timeout=s.collector_timeout_seconds,
        max_redirects=s.collector_max_redirects,
    )

    if result.not_modified:
        return result
    if result.status >= 400:
        raise FetchError(f"HTTP {result.status}")
    if result.content_type and allowed_content_types:
        if not any(result.content_type == t for t in allowed_content_types):
            raise FetchError(f"disallowed content-type: {result.content_type}")
    return result


async def fetch_with_retries(url: str, **kwargs) -> FetchResult:
    """Wrap `fetch` with exponential backoff on transient errors.
    SSRF errors are NOT retried (they are deterministic rejections)."""
    s = get_settings()
    last: Exception | None = None
    for attempt in range(s.collector_max_retries):
        try:
            return await fetch(url, **kwargs)
        except SSRFError:
            raise
        except (FetchError, httpx.HTTPError) as exc:
            last = exc
            if attempt < s.collector_max_retries - 1:
                await asyncio.sleep(s.collector_backoff_base_seconds * (2**attempt))
    raise FetchError(f"all {s.collector_max_retries} attempts failed: {last}")
