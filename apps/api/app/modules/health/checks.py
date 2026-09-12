"""Real dependency health probes.

Each probe actually opens a connection to the target service. Nothing here is
mocked: if a service is down, its check fails and readiness reflects it.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker

log = get_logger("health")

_TIMEOUT = 3.0  # seconds per probe


@dataclass
class ProbeResult:
    name: str
    ok: bool
    latency_ms: float | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        d: dict = {"ok": self.ok}
        if self.latency_ms is not None:
            d["latency_ms"] = round(self.latency_ms, 1)
        if self.error:
            d["error"] = self.error
        return d


async def _timed(name: str, coro) -> ProbeResult:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout=_TIMEOUT)
        return ProbeResult(name, True, (time.perf_counter() - start) * 1000)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(name, False, error=f"{type(exc).__name__}: {exc}"[:200])


# --------------------------------------------------------------------------- #
async def _check_postgres() -> None:
    async with get_sessionmaker()() as session:
        await session.execute(text("SELECT 1"))


async def _check_redis() -> None:
    import redis.asyncio as aioredis

    s = get_settings()
    client = aioredis.Redis(
        host=s.redis_host,
        port=s.redis_port,
        db=s.redis_db,
        password=s.redis_password,
        socket_connect_timeout=_TIMEOUT,
    )
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _check_minio() -> None:
    from minio import Minio

    s = get_settings()

    def _probe() -> None:
        client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_secure,
        )
        # list_buckets requires a live, authenticated connection.
        client.list_buckets()

    await asyncio.to_thread(_probe)


async def _check_opensearch() -> None:
    import httpx

    s = get_settings()
    scheme = "https" if s.opensearch_use_ssl else "http"
    url = f"{scheme}://{s.opensearch_host}:{s.opensearch_port}/_cluster/health"
    auth = None
    if s.opensearch_user and s.opensearch_password:
        auth = (s.opensearch_user, s.opensearch_password)
    async with httpx.AsyncClient(verify=False, timeout=_TIMEOUT) as client:
        resp = await client.get(url, auth=auth)
        resp.raise_for_status()
        status = resp.json().get("status")
        if status == "red":
            raise RuntimeError("cluster status is red")


async def _check_neo4j() -> None:
    from neo4j import AsyncGraphDatabase

    s = get_settings()
    driver = AsyncGraphDatabase.driver(
        s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password)
    )
    try:
        await driver.verify_connectivity()
    finally:
        await driver.close()


PROBES = {
    "postgres": _check_postgres,
    "redis": _check_redis,
    "minio": _check_minio,
    "opensearch": _check_opensearch,
    "neo4j": _check_neo4j,
}


async def run_all_probes() -> dict[str, ProbeResult]:
    results = await asyncio.gather(
        *[_timed(name, probe()) for name, probe in PROBES.items()]
    )
    return {r.name: r for r in results}
