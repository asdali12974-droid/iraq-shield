"""telegram: source class, verification, telegram channel fields, forwarded_from

Revision ID: 0005_telegram
Revises: 0004_web_collector
Create Date: 2026-08-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_telegram"
down_revision: str | None = "0004_web_collector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("source_class", sa.String(24), nullable=True))
    op.add_column("sources", sa.Column("last_cursor", sa.String(128), nullable=True))
    op.add_column("sources", sa.Column("telegram_username", sa.String(64), nullable=True))
    op.add_column("sources", sa.Column("telegram_channel_id", sa.BigInteger(), nullable=True))
    op.add_column("sources", sa.Column("telegram_title", sa.String(256), nullable=True))
    op.add_column("sources", sa.Column("verification_status", sa.String(24), nullable=True))
    op.add_column("sources", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))

    op.create_check_constraint(
        "ck_sources_class", "sources",
        "source_class IS NULL OR source_class IN "
        "('OFFICIAL','POLITICAL_MEDIA','MEDIA_OTHER')",
    )
    op.create_check_constraint(
        "ck_sources_verification", "sources",
        "verification_status IS NULL OR verification_status IN "
        "('pending','verified','failed','unsupported')",
    )
    op.create_index("ix_sources_tg_username", "sources", ["telegram_username"])

    # Extend relation types with forwarded_from.
    op.drop_constraint("ck_relation_type", "content_relations", type_="check")
    op.create_check_constraint(
        "ck_relation_type", "content_relations",
        "relation_type IN ('same_event_candidate','forwarded_from')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_relation_type", "content_relations", type_="check")
    op.create_check_constraint(
        "ck_relation_type", "content_relations", "relation_type IN ('same_event_candidate')"
    )
    op.drop_index("ix_sources_tg_username", table_name="sources")
    op.drop_constraint("ck_sources_verification", "sources", type_="check")
    op.drop_constraint("ck_sources_class", "sources", type_="check")
    for col in (
        "verified_at", "verification_status", "telegram_title", "telegram_channel_id",
        "telegram_username", "last_cursor", "source_class",
    ):
        op.drop_column("sources", col)
