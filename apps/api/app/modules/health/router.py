"""Health & readiness endpoints.

- GET /health        liveness: is the process up? (no dependency checks)
- GET /health/ready  readiness: are all backing services reachable?
"""
from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.modules.health.checks import run_all_probes

router = APIRouter()


@router.get("/health", tags=["health"])
async def health():
    s = get_settings()
    return {"status": "ok", "service": s.app_name, "environment": s.environment}


@router.get("/health/ready", tags=["health"])
async def readiness(response: Response):
    results = await run_all_probes()
    services = {name: r.as_dict() for name, r in results.items()}
    all_ok = all(r.ok for r in results.values())
    response.status_code = (
        status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return {"status": "ready" if all_ok else "degraded", "services": services}
