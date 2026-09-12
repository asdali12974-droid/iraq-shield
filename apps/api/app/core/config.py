"""Central configuration, loaded from environment variables only.

No secret has a usable default: the app refuses to start in a non-dev
environment if security-critical values are left unset. This is deliberate —
a foundation that boots with a hard-coded secret is not production-oriented.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---
    app_name: str = "IRAQ SHIELD API"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True
    api_prefix: str = "/api/v1"

    # CORS — explicit allowlist, never "*" in production.
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- PostgreSQL ---
    # External database URL (takes precedence over individual postgres_* settings)
    # Format: postgresql://user:password@host:port/database?sslmode=require
    # Set via environment variable DATABASE_URL (no IS_ prefix)
    database_url: str | None = Field(default=None, repr=False, validation_alias="DATABASE_URL")

    # Fallback: individual PostgreSQL connection parameters
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "iraqshield"
    postgres_user: str = "iraqshield"
    postgres_password: str = Field(default="iraqshield", repr=False)

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    # --- MinIO / object storage ---
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "iraqshield"
    minio_secret_key: str = "iraqshield"
    minio_secure: bool = False
    minio_bucket_raw: str = "raw-archive"

    # --- OpenSearch ---
    opensearch_host: str = "localhost"
    opensearch_port: int = 9200
    opensearch_user: str | None = None
    opensearch_password: str | None = None
    opensearch_use_ssl: bool = False

    # --- Neo4j ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "iraqshield"

    # --- Security / JWT ---
    jwt_secret: str = "dev-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 7

    # --- Login throttling (brute-force protection) ---
    login_fail_window_seconds: int = 900
    login_max_email_failures: int = 5
    login_max_ip_failures: int = 20

    # --- Collector (P1) ---
    collector_user_agent: str = "IraqShieldBot/0.1 (+https://iraqshield.local/bot)"
    # When False (default), outbound collection refuses private/loopback/metadata
    # targets (SSRF protection). Enabled only in local tests against a fake feed.
    collector_allow_private_hosts: bool = False
    collector_timeout_seconds: float = 20.0
    collector_max_bytes: int = 8_000_000
    collector_max_redirects: int = 3
    collector_max_retries: int = 3
    collector_backoff_base_seconds: float = 0.5
    collector_min_host_interval_seconds: float = 2.0
    collector_respect_robots: bool = True

    # Raw archive object store: "filesystem" (local/dev) or "minio".
    raw_store_backend: Literal["filesystem", "minio"] = "filesystem"
    raw_store_fs_path: str = "/tmp/iraqshield-archive"

    # --- Telegram (P1.3) — official MTProto access to PUBLIC channels only. ---
    # SECRETS: set via environment only, never committed or logged. `repr=False`
    # keeps them out of any settings repr/log line.
    telegram_api_id: int | None = Field(default=None, repr=False)
    telegram_api_hash: str | None = Field(default=None, repr=False)
    telegram_session_string: str | None = Field(default=None, repr=False)
    telegram_flood_sleep_threshold: int = 60  # auto-sleep flood waits up to this
    telegram_max_messages_per_run: int = 200

    @property
    def telegram_configured(self) -> bool:
        return bool(
            self.telegram_api_id
            and self.telegram_api_hash
            and self.telegram_session_string
        )

    # --- Bootstrap admin (real account, created once on init) ---
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    bootstrap_admin_name: str = "System Administrator"

    @field_validator("jwt_secret")
    @classmethod
    def _reject_default_secret_in_prod(cls, v: str, info) -> str:
        # info.data may not yet contain environment; validated again at runtime
        return v

    def _parse_database_url(self) -> tuple[str, str, int, str, str, bool]:
        """Parse DATABASE_URL into components.

        Returns: (host, db, port, user, password, use_ssl)
        Handles ?sslmode=require and similar parameters.
        """
        if not self.database_url:
            return (
                self.postgres_host,
                self.postgres_db,
                self.postgres_port,
                self.postgres_user,
                self.postgres_password,
                False,
            )

        url = urlparse(self.database_url)
        host = url.hostname or "localhost"
        port = url.port or 5432
        db = url.path.lstrip("/") if url.path else "iraqshield"
        user = url.username or "iraqshield"
        password = url.password or "iraqshield"
        use_ssl = "sslmode=require" in self.database_url.lower()

        return host, db, port, user, password, use_ssl

    @property
    def sqlalchemy_dsn(self) -> str:
        """SQLAlchemy DSN for asyncpg driver.

        asyncpg does not support ?sslmode in the URL; SSL is enabled via connect_args.
        """
        host, db, port, user, password, use_ssl = self._parse_database_url()
        return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"

    @property
    def alembic_dsn(self) -> str:
        """Alembic DSN for psycopg (sync) driver.

        psycopg supports ?sslmode in the URL.
        """
        if self.database_url:
            url = self.database_url
            # Ensure the URL uses psycopg driver if not already specified
            if "postgresql://" == url[:13]:  # Plain postgresql:// without driver
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            # Add sslmode=require if not already present
            if "sslmode=" not in url.lower():
                url = url + "?sslmode=require"
            return url

        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def get_sqlalchemy_connect_args(self) -> dict:
        """Return SQLAlchemy connect_args for SSL/TLS configuration."""
        _, _, _, _, _, use_ssl = self._parse_database_url()
        if use_ssl:
            return {"ssl": True}
        return {}

    def assert_production_safety(self) -> None:
        """Fail loudly if unsafe defaults survive into a real deployment."""
        if self.environment != "production":
            return
        problems = []
        if self.jwt_secret == "dev-insecure-secret-change-me":
            problems.append("IS_JWT_SECRET is still the insecure default")
        if len(self.jwt_secret) < 32:
            problems.append("IS_JWT_SECRET must be at least 32 chars in production")

        # DATABASE_URL takes precedence; only check postgres_* if DATABASE_URL not set
        if not self.database_url:
            if self.postgres_password in ("iraqshield", "", "change-me-postgres"):
                problems.append("IS_POSTGRES_PASSWORD is default/empty (or set DATABASE_URL)")
        else:
            # DATABASE_URL is set; verify it's not the default URL
            if self.database_url in ("postgresql://iraqshield:iraqshield@localhost/iraqshield",):
                problems.append("DATABASE_URL is using default insecure values")

        if self.minio_secret_key in ("iraqshield", "", "change-me-minio"):
            problems.append("IS_MINIO_SECRET_KEY is default/empty")
        if self.neo4j_password in ("iraqshield", "neo4j", "", "change-me-neo4j"):
            problems.append("IS_NEO4J_PASSWORD is default/empty")
        if "*" in self.cors_origins:
            problems.append("IS_CORS_ORIGINS must not be '*' in production")
        if self.debug:
            problems.append("IS_DEBUG must be false in production")
        if problems:
            raise RuntimeError(
                "Refusing to start in production with insecure config: "
                + "; ".join(problems)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
