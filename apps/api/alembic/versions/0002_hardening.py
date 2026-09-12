"""hardening: refresh_tokens table + CHECK constraints

Revision ID: 0002_hardening
Revises: 0001_initial
Create Date: 2026-08-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_hardening"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- refresh_tokens (revocable sessions) ---
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_user_active", "refresh_tokens", ["user_id", "revoked_at"])

    # --- data-integrity CHECK constraints ---
    op.create_check_constraint(
        "ck_users_clearance_range", "users", "clearance_level >= 0 AND clearance_level <= 5"
    )
    op.create_check_constraint(
        "ck_audit_outcome", "audit_log", "outcome IN ('success', 'failure')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_outcome", "audit_log", type_="check")
    op.drop_constraint("ck_users_clearance_range", "users", type_="check")
    op.drop_index("ix_refresh_user_active", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
