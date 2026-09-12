"""collection: sources, collection_runs, historical raw_archive

Revision ID: 0003_collection
Revises: 0002_hardening
Create Date: 2026-08-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_collection"
down_revision: str | None = "0002_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("country_region", sa.String(64), nullable=True),
        sa.Column("category", sa.String(24), nullable=True),
        sa.Column("reliability", sa.String(1), nullable=False, server_default="C"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("collection_interval_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("etag", sa.String(512), nullable=True),
        sa.Column("last_modified", sa.String(128), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(16), nullable=True),
        sa.Column("last_error", sa.String(1024), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("uq_sources_url", "sources", ["url"], unique=True)
    op.create_index("ix_sources_enabled", "sources", ["enabled"])
    op.create_check_constraint(
        "ck_sources_type", "sources",
        "source_type IN ('NEWS','RSS','WEBSITE','TELEGRAM_PUBLIC')",
    )
    op.create_check_constraint(
        "ck_sources_category", "sources",
        "category IS NULL OR category IN "
        "('security','political','economic','social','cyber','regional')",
    )
    op.create_check_constraint(
        "ck_sources_reliability", "sources", "reliability IN ('A','B','C','D','E','F')"
    )
    op.create_check_constraint(
        "ck_sources_interval", "sources", "collection_interval_seconds >= 60"
    )

    op.create_table(
        "collection_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="success"),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("items_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_duplicate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_versioned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(1024), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_collection_runs_source_id", "collection_runs", ["source_id"])
    op.create_index("ix_runs_source_started", "collection_runs", ["source_id", "started_at"])
    op.create_check_constraint(
        "ck_runs_status", "collection_runs",
        "status IN ('success','failure','partial','skipped')",
    )

    op.create_table(
        "raw_archive",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("canonical_url", sa.String(2048), nullable=True),
        sa.Column("external_id", sa.String(512), nullable=True),
        sa.Column("title", sa.String(1024), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("http_headers", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("raw_ref", sa.String(512), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_raw_archive_source_id", "raw_archive", ["source_id"])
    op.create_index("ix_archive_content_hash", "raw_archive", ["content_hash"])
    op.create_index("ix_archive_fingerprint", "raw_archive", ["fingerprint"])
    op.create_index("ix_archive_source_extid", "raw_archive", ["source_id", "external_id"])
    op.create_index("ix_archive_source_current", "raw_archive", ["source_id", "is_current"])

    # Historical archive: rows are never deleted. (Updates are allowed only for
    # the is_current/supersedes bookkeeping, done by the application.)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION iraqshield_deny_delete()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is delete-protected (historical archive)', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER raw_archive_no_delete
        BEFORE DELETE ON raw_archive
        FOR EACH ROW EXECUTE FUNCTION iraqshield_deny_delete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS raw_archive_no_delete ON raw_archive")
    op.drop_table("raw_archive")
    op.drop_table("collection_runs")
    op.drop_table("sources")
    op.execute("DROP FUNCTION IF EXISTS iraqshield_deny_delete()")
