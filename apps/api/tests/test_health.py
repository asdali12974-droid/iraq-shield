"""Health & readiness.

The readiness endpoint performs REAL connection probes against every backing
service. These tests prove that:
  (1) liveness is independent of dependencies,
  (2) readiness reports every expected service and reflects its true state,
  (3) the datastores that are running are reported healthy.

The strict "every service green" assertion runs only when IS_TEST_FULL_STACK=1
(the full docker compose stack is up). This keeps the suite runnable in a
partial environment without ever faking a service as healthy.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

FULL_STACK = os.getenv("IS_TEST_FULL_STACK") == "1"
EXPECTED = ("postgres", "redis", "minio", "opensearch", "neo4j")


async def test_liveness(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_readiness_reports_every_service(client):
    resp = await client.get("/health/ready")
    body = resp.json()
    for svc in EXPECTED:
        assert svc in body["services"], f"{svc} missing from readiness report"
    # Datastores that must be running for the rest of the suite:
    assert body["services"]["postgres"]["ok"] is True, body["services"]["postgres"]
    assert body["services"]["redis"]["ok"] is True, body["services"]["redis"]


async def test_readiness_probes_are_real(client):
    """A probe result carries either a real latency (up) or a real error
    string (down) — never a hard-coded 'ok'."""
    body = (await client.get("/health/ready")).json()
    for _, info in body["services"].items():
        if info["ok"]:
            assert "latency_ms" in info
        else:
            assert info.get("error"), "a down service must report a real error"


@pytest.mark.skipif(not FULL_STACK, reason="requires full docker compose stack")
async def test_readiness_full_stack(client):
    resp = await client.get("/health/ready")
    body = resp.json()
    assert resp.status_code == 200, body
    assert body["status"] == "ready"
    assert all(info["ok"] for info in body["services"].values())
