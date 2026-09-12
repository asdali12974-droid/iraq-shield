"""Test fixtures.

Integration tests run against the REAL backing services started via
docker compose (postgres, redis, minio, opensearch, neo4j) — there are no
mocks. A dedicated `iraqshield_test` database is created and migrated so tests
never touch development data.
"""
from __future__ import annotations

import os

import pytest_asyncio

# --- Point the app at the test database BEFORE importing app modules. ---
os.environ.setdefault("IS_ENVIRONMENT", "development")
os.environ.setdefault("IS_LOG_JSON", "false")
# Isolate throttle/rate-limit state in a dedicated Redis DB, never dev db 0.
os.environ.setdefault("IS_REDIS_HOST", os.getenv("IS_REDIS_HOST", "localhost"))
os.environ.setdefault("IS_REDIS_DB", "15")
os.environ.setdefault("IS_POSTGRES_HOST", os.getenv("IS_POSTGRES_HOST", "localhost"))
os.environ.setdefault("IS_POSTGRES_PORT", os.getenv("IS_POSTGRES_PORT", "5432"))
os.environ.setdefault("IS_POSTGRES_USER", os.getenv("IS_POSTGRES_USER", "iraqshield"))
os.environ.setdefault(
    "IS_POSTGRES_PASSWORD", os.getenv("IS_POSTGRES_PASSWORD", "iraqshield")
)
os.environ["IS_POSTGRES_DB"] = "iraqshield_test"
os.environ.setdefault("IS_JWT_SECRET", "test-secret-not-for-production")
os.environ.setdefault("IS_BOOTSTRAP_ADMIN_EMAIL", "admin@iraqshield.test")
os.environ.setdefault("IS_BOOTSTRAP_ADMIN_PASSWORD", "admin-test-password-123")

import asyncpg  # noqa: E402
import httpx  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.config import get_settings  # noqa: E402

TEST_DB = "iraqshield_test"


async def _ensure_test_db() -> None:
    s = get_settings()
    dsn = (
        f"postgresql://{s.postgres_user}:{s.postgres_password}"
        f"@{s.postgres_host}:{s.postgres_port}/postgres"
    )
    conn = await asyncpg.connect(dsn)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()


def _run_migrations() -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    command.upgrade(cfg, "head")


async def _reset_collection_tables() -> None:
    """Start every run from a clean collection state.

    The test database persists across runs, so accumulated sources/archive rows
    would otherwise collide on unique URLs (e.g. reused localhost ports, fixed
    Telegram usernames). TRUNCATE bypasses the append-only DELETE guard on
    raw_archive, so this only resets test data — never IAM or audit tables.
    """
    s = get_settings()
    dsn = (
        f"postgresql://{s.postgres_user}:{s.postgres_password}"
        f"@{s.postgres_host}:{s.postgres_port}/{TEST_DB}"
    )
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "TRUNCATE raw_archive, content_relations, collection_runs, sources "
            "RESTART IDENTITY CASCADE"
        )
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_database():
    get_settings.cache_clear()
    await _ensure_test_db()
    _run_migrations()
    await _reset_collection_tables()
    # Seed RBAC + admin against the freshly migrated test DB.
    from app.modules.iam.bootstrap import run_bootstrap

    await run_bootstrap()
    # Start throttle counters from a clean slate.
    from app.core.redis import close_redis, get_redis

    try:
        await get_redis().flushdb()
    except Exception:
        pass
    yield
    from app.db.session import dispose_engine

    await dispose_engine()
    await close_redis()


@pytest_asyncio.fixture
async def client():
    from app.main import app

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            yield ac


@pytest_asyncio.fixture
async def db_session():
    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as session:
        yield session


@pytest_asyncio.fixture
async def admin_token(client) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@iraqshield.test", "password": "admin-test-password-123"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def viewer_token(client, db_session) -> str:
    """Create (idempotently) a viewer user and return its access token."""
    from app.modules.iam.service import create_user, get_user_by_email

    email = "viewer@iraqshield.test"
    password = "viewer-test-password-123"
    if await get_user_by_email(db_session, email) is None:
        await create_user(
            db_session,
            email=email,
            password=password,
            full_name="Test Viewer",
            role_names=["viewer"],
        )
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]
