"""event_model: analyst-driven events and archive links

Revision ID: 0008_event_model
Revises: 0007_fulltext_search
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "0008_event_model"
down_revision: str | None = "0007_fulltext_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "title",
            sa.String(512),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.String(4096),
            nullable=True,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "severity",
            sa.String(1),
            nullable=False,
            server_default="C",
        ),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="0.5",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_events_status",
        "events",
        ["status"],
    )

    op.create_index(
        "ix_events_severity",
        "events",
        ["severity"],
    )

    op.create_index(
        "ix_events_created_at",
        "events",
        ["created_at"],
    )

    op.create_index(
        "ix_events_created_by",
        "events",
        ["created_by"],
    )

    op.create_index(
        "ix_events_occurred_at",
        "events",
        ["occurred_at"],
    )

    op.create_check_constraint(
        "ck_events_status",
        "events",
        "status IN ('pending','confirmed','dismissed','closed')",
    )

    op.create_check_constraint(
        "ck_events_severity",
        "events",
        "severity IN ('A','B','C','D','E','F')",
    )

    op.create_check_constraint(
        "ck_events_confidence",
        "events",
        "confidence >= 0.0 AND confidence <= 1.0",
    )

    op.create_table(
        "event_archive",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "archive_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "linked_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["archive_id"],
            ["raw_archive.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["linked_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_event_archive_linked_at",
        "event_archive",
        ["linked_at"],
    )

    op.create_index(
        "ix_event_archive_linked_by",
        "event_archive",
        ["linked_by"],
    )

    op.create_index(
        "ix_event_archive_archive_id",
        "event_archive",
        ["archive_id"],
    )


def downgrade() -> None:
    op.drop_table("event_archive")
    op.drop_table("events")