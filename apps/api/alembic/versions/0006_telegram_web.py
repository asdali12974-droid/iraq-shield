"""telegram_web: add TELEGRAM_PUBLIC_WEB to source_type check constraint

Revision ID: 0006_telegram_web
Revises: 0005_telegram
Create Date: 2026-09-10
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_telegram_web"
down_revision: str | None = "0005_telegram"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_sources_type", "sources", type_="check")
    op.create_check_constraint(
        "ck_sources_type", "sources",
        "source_type IN ('NEWS','RSS','WEBSITE','TELEGRAM_PUBLIC','TELEGRAM_PUBLIC_WEB')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sources_type", "sources", type_="check")
    op.create_check_constraint(
        "ck_sources_type", "sources",
        "source_type IN ('NEWS','RSS','WEBSITE','TELEGRAM_PUBLIC')",
    )
