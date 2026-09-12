"""web collector: extraction config, extracted article fields, job counters, relations

Revision ID: 0004_web_collector
Revises: 0003_collection
Create Date: 2026-08-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_web_collector"
down_revision: str | None = "0003_collection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("extraction_config", postgresql.JSONB(), nullable=True))

    op.add_column("raw_archive", sa.Column("author", sa.String(256), nullable=True))
    op.add_column("raw_archive", sa.Column("extracted", postgresql.JSONB(), nullable=True))

    op.add_column(
        "collection_runs",
        sa.Column("items_discovered", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "collection_runs",
        sa.Column("items_failed", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "content_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("from_archive_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_archive_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["from_archive_id"], ["raw_archive.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_archive_id"], ["raw_archive.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_content_relations_from_archive_id", "content_relations", ["from_archive_id"])
    op.create_index("ix_content_relations_to_archive_id", "content_relations", ["to_archive_id"])
    op.create_index(
        "uq_relation", "content_relations",
        ["from_archive_id", "to_archive_id", "relation_type"], unique=True,
    )
    op.create_check_constraint(
        "ck_relation_type", "content_relations", "relation_type IN ('same_event_candidate')"
    )

    # Allow the new 'cancelled' run status.
    op.drop_constraint("ck_runs_status", "collection_runs", type_="check")
    op.create_check_constraint(
        "ck_runs_status", "collection_runs",
        "status IN ('success','failure','partial','skipped','cancelled')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_runs_status", "collection_runs", type_="check")
    op.create_check_constraint(
        "ck_runs_status", "collection_runs",
        "status IN ('success','failure','partial','skipped')",
    )
    op.drop_table("content_relations")
    op.drop_column("collection_runs", "items_failed")
    op.drop_column("collection_runs", "items_discovered")
    op.drop_column("raw_archive", "extracted")
    op.drop_column("raw_archive", "author")
    op.drop_column("sources", "extraction_config")
