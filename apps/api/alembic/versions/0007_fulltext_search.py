"""full-text search indexes

Revision ID: 0007_fulltext_search
Revises: 0006_telegram_web
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0007_fulltext_search"
down_revision: str | None = "0006_telegram_web"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_archive_title_gin
        ON raw_archive
        USING gin (to_tsvector('english', title))
        """
    )

    op.execute(
        """
        CREATE INDEX ix_archive_extracted_text_gin
        ON raw_archive
        USING gin (
            to_tsvector(
                'english',
                COALESCE(extracted->>'text', '')
            )
        )
        """
    )

    op.execute(
        """
        CREATE INDEX ix_archive_title_author_gin
        ON raw_archive
        USING gin (
            to_tsvector(
                'english',
                COALESCE(title, '') || ' ' || COALESCE(author, '')
            )
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_archive_title_author_gin"
    )

    op.execute(
        "DROP INDEX IF EXISTS ix_archive_extracted_text_gin"
    )

    op.execute(
        "DROP INDEX IF EXISTS ix_archive_title_gin"
    )