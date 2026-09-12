"""entity_foundation: analyst-driven entities with archive/event linking

Revision ID: 0009_entity_foundation
Revises: 0008_event_model
Create Date: 2026-09-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_entity_foundation"
down_revision: str | None = "0008_event_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create entities, archive_entity, event_entity, and entity_relationships tables."""
    # Create entities table
    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(24), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("description", sa.String(2048), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_entities_confidence"),
        sa.CheckConstraint("status IN ('pending', 'confirmed', 'dismissed', 'archived')", name="ck_entities_status"),
    )
    op.create_index("ix_entities_status", "entities", ["status"])
    op.create_index("ix_entities_entity_type", "entities", ["entity_type"])
    op.create_index("ix_entities_created_by", "entities", ["created_by"])

    # Create archive_entity table (analyst-driven linking)
    op.create_table(
        "archive_entity",
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("archive_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("linked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["archive_id"], ["raw_archive.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("entity_id", "archive_id"),
    )
    op.create_index("ix_archive_entity_archive_id", "archive_entity", ["archive_id"])
    op.create_index("ix_archive_entity_linked_by", "archive_entity", ["linked_by"])

    # Create event_entity table (analyst-driven linking)
    op.create_table(
        "event_entity",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("linked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("event_id", "entity_id"),
    )
    op.create_index("ix_event_entity_event_id", "event_entity", ["event_id"])
    op.create_index("ix_event_entity_linked_by", "event_entity", ["linked_by"])

    # Create entity_relationships table (immutable, directed, typed)
    op.create_table(
        "entity_relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["from_entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_entity_relationship_confidence"),
        sa.UniqueConstraint("from_entity_id", "to_entity_id", "relation_type", name="uq_entity_relationship"),
    )
    op.create_index("ix_entity_relationship_to", "entity_relationships", ["to_entity_id"])
    op.create_index("ix_entity_relationship_type", "entity_relationships", ["relation_type"])


def downgrade() -> None:
    """Drop all entity tables."""
    op.drop_index("ix_entity_relationship_type", table_name="entity_relationships")
    op.drop_index("ix_entity_relationship_to", table_name="entity_relationships")
    op.drop_table("entity_relationships")

    op.drop_index("ix_event_entity_linked_by", table_name="event_entity")
    op.drop_index("ix_event_entity_event_id", table_name="event_entity")
    op.drop_table("event_entity")

    op.drop_index("ix_archive_entity_linked_by", table_name="archive_entity")
    op.drop_index("ix_archive_entity_archive_id", table_name="archive_entity")
    op.drop_table("archive_entity")

    op.drop_index("ix_entities_created_by", table_name="entities")
    op.drop_index("ix_entities_entity_type", table_name="entities")
    op.drop_index("ix_entities_status", table_name="entities")
    op.drop_table("entities")
