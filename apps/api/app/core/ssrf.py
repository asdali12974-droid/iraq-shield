"""SSRF protection for outbound collection.

A user (via the Source Registry) supplies URLs the platform will fetch. Without
guarding, that is a classic SSRF sink: an attacker could point a source at
http://169.254.169.254/ (cloud metadata), http://localhost:6379/ (Redis), or an
internal admin panel. This module validates a URL's scheme and — crucially — the
IP addresses its host actually resolves to, refusing anything private, loopback,
link-local (incl. metadata), multicast, or reserved.

Validation resolves DNS and checks EVERY returned address, so a hostname that
resolves to an internal IP is rejected. Each redirect hop is re-validated by the
fetcher. `collector_allow_private_hosts` (default False) lifts the block only for
local tests against a fake feed server.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.core.config import get_settings

ALLOWED_SCHEMES = {"http", "https"}
# Hostnames that must never be fetched regardless of resolution.
BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata",
}


class SSRFError(Exception):
    """Raised when a URL targets a disallowed host/IP."""


@dataclass(frozen=True)
class ValidatedTarget:
    scheme: str
    host: str
    port: int
    ips: tuple[str, ...]


def _ip_blocked(ip: ipaddress._BaseAddress) -> bool:
    # Normalize IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) to its IPv4 form.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # includes 169.254.0.0/16 (cloud metadata)
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFError(f"cannot resolve host: {host}") from exc
    ips = sorted({info[4][0] for info in infos})
    if not ips:
        raise SSRFError(f"host resolves to no address: {host}")
    return ips


def validate_url(url: str) -> ValidatedTarget:
    """Validate a URL for outbound fetching. Raises SSRFError if disallowed."""
    settings = get_settings()
    parts = urlsplit(url)

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise SSRFError(f"scheme not allowed: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise SSRFError("URL has no host")

    if settings.collector_allow_private_hosts:
        # Local/test mode: skip IP checks but still resolve for a real target.
        try:
            ips = _resolve(host)
        except SSRFError:
            ips = ()
        port = parts.port or (443 if parts.scheme == "https" else 80)
        return ValidatedTarget(parts.scheme.lower(), host, port, tuple(ips))

    if host.lower() in BLOCKED_HOSTNAMES:
        raise SSRFError(f"host is blocklisted: {host}")

    # A literal IP host is validated directly; otherwise resolve and validate all.
    candidate_ips: list[str]
    try:
        ipaddress.ip_address(host)
        candidate_ips = [host]
    except ValueError:
        candidate_ips = _resolve(host)

    for raw in candidate_ips:
        ip = ipaddress.ip_address(raw)
        if _ip_blocked(ip):
            raise SSRFError(f"host {host} resolves to a blocked address: {raw}")

    port = parts.port or (443 if parts.scheme == "https" else 80)
    return ValidatedTarget(parts.scheme.lower(), host, port, tuple(candidate_ips))


def validate_url_shallow(url: str) -> None:
    """Input-time check for a user-supplied source URL: scheme, host present,
    blocklisted hostnames, and literal private IPs — WITHOUT DNS resolution (so
    adding a source never depends on network). The strict, DNS-resolving
    `validate_url` still runs at fetch time and is the real SSRF enforcement."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise SSRFError(f"scheme not allowed: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise SSRFError("URL has no host")
    if get_settings().collector_allow_private_hosts:
        return
    if host.lower() in BLOCKED_HOSTNAMES:
        raise SSRFError(f"host is blocklisted: {host}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # a hostname; resolution is deferred to fetch time
    if _ip_blocked(ip):
        raise SSRFError(f"host is a blocked address: {host}")
