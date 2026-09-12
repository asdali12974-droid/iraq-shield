"""Login brute-force throttling backed by Redis.

Counts failed logins per email and per source IP within a sliding window. When
a threshold is exceeded, logins are refused with a Retry-After until the window
elapses. Fails OPEN if Redis is unavailable (availability over lockout) but logs
loudly — a sovereign on-prem deployment must not be self-DoS'able by a Redis
blip, and the audit log still records every attempt.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger("throttle")


@dataclass
class ThrottleState:
    locked: bool
    retry_after: int = 0


def _keys(email: str, ip: str | None) -> tuple[str, str]:
    return (f"lf:e:{email.lower()}", f"lf:i:{ip or 'unknown'}")


async def check(email: str, ip: str | None) -> ThrottleState:
    s = get_settings()
    ek, ik = _keys(email, ip)
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.get(ek)
        pipe.ttl(ek)
        pipe.get(ik)
        pipe.ttl(ik)
        ec, ettl, ic, ittl = await pipe.execute()
        if int(ec or 0) >= s.login_max_email_failures:
            return ThrottleState(True, max(int(ettl or 1), 1))
        if int(ic or 0) >= s.login_max_ip_failures:
            return ThrottleState(True, max(int(ittl or 1), 1))
        return ThrottleState(False)
    except Exception as exc:  # noqa: BLE001 — fail open, but never silently
        log.warning("throttle_check_failed_open", error=str(exc))
        return ThrottleState(False)


async def register_failure(email: str, ip: str | None) -> None:
    s = get_settings()
    ek, ik = _keys(email, ip)
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.incr(ek)
        pipe.expire(ek, s.login_fail_window_seconds, nx=True)
        pipe.incr(ik)
        pipe.expire(ik, s.login_fail_window_seconds, nx=True)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        log.warning("throttle_register_failed", error=str(exc))


async def reset(email: str, ip: str | None) -> None:
    ek, ik = _keys(email, ip)
    try:
        await get_redis().delete(ek, ik)
    except Exception as exc:  # noqa: BLE001
        log.warning("throttle_reset_failed", error=str(exc))
