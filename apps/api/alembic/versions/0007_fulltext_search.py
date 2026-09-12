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
    # Full-text search index for archive titles.
    op.create_index(
        "ix_archive_title_gin",
        "raw_archive",
        [op.text("to_tsvector('english', title)")],
        postgresql_using="gin",
    )

    # Full-text search index for extracted article text.
    op.create_index(
        "ix_archive_extracted_text_gin",
        "raw_archive",
        [
            op.text(
                "to_tsvector('english', COALESCE(extracted->>'text', ''))"
            )
        ],
        postgresql_using="gin",
    )

    # Combined full-text search index for title + author.
    op.create_index(
        "ix_archive_title_author_gin",
        "raw_archive",
        [
            op.text(
                "to_tsvector('english', "
                "COALESCE(title, '') || ' ' || COALESCE(author, ''))"
            )
        ],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_archive_title_author_gin",
        table_name="raw_archive",
    )

    op.drop_index(
        "ix_archive_extracted_text_gin",
        table_name="raw_archive",
    )

    op.drop_index(
        "ix_archive_title_gin",
        table_name="raw_archive",
    )