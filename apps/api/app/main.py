"""IRAQ SHIELD API أ¢â‚¬â€‌ application factory (P0 foundation)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.redis import close_redis
from app.db.session import dispose_engine
from app.modules.audit.router import router as audit_router
from app.modules.collection.router import router as collection_router
from app.modules.health.router import router as health_router
from app.modules.iam.router import router as iam_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(level=s.log_level, json_output=s.log_json)
    log = get_logger("startup")
    s.assert_production_safety()
    log.info(
        "api_starting",
        environment=s.environment,
        app=s.app_name,
    )
    yield
    await dispose_engine()
    await close_redis()
    log.info("api_stopped")


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=s.app_name,
        version="0.1.0",
        description="OSINT & intelligence platform أ¢â‚¬â€‌ P0 foundation (IAM, audit, health).",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "https://iraq-shield-web-production.up.railway.app"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(app)

    # Health lives at the root (probes hit /health, /health/ready).
    app.include_router(health_router)
    # Versioned API surface.
    app.include_router(iam_router, prefix=s.api_prefix)
    app.include_router(audit_router, prefix=s.api_prefix)
    app.include_router(collection_router, prefix=s.api_prefix)

    return app


app = create_app()








