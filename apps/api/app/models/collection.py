"""Collection domain: source registry, historical raw archive, run history.

The raw archive is append-oriented: a new collection that finds changed content
inserts a NEW version row rather than overwriting the old one. Only the
`is_current`/`supersedes_id` flags are ever updated; content columns are never
rewritten, and rows are never deleted (enforced by a DB trigger).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

SOURCE_TYPES = ("NEWS", "RSS", "WEBSITE", "TELEGRAM_PUBLIC", "TELEGRAM_PUBLIC_WEB")
CATEGORIES = ("security", "political", "economic", "social", "cyber", "regional")
RELIABILITY = ("A", "B", "C", "D", "E", "F")
RUN_STATUSES = ("success", "failure", "partial", "skipped", "cancelled")
# Editorial classification (analyst/admin assigned) — separate from reliability.
SOURCE_CLASSES = ("OFFICIAL", "POLITICAL_MEDIA", "MEDIA_OTHER")
# Verification of a source's channel/endpoint (never faked without connectivity).
VERIFICATION_STATUSES = ("pending", "verified", "failed", "unsupported")

# Health thresholds.
_DEGRADED_AFTER = 1  # >=1 consecutive failure => degraded
_FAILED_AFTER = 3  # >=3 consecutive failures => failed


class Source(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    country_region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(24), nullable=True)
    reliability: Mapped[str] = mapped_column(String(1), nullable=False, default="C")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    collection_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3600
    )

    # Conditional-request state (idempotency / bandwidth).
    etag: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Health counters.
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Optional per-source extraction/collection configuration (WEBSITE sources):
    # {"mode": "article"|"index", "link_selector": "...", "max_articles": N,
    #  "title_selector": "...", "body_selector": "...", ...}. Generic extraction
    # is used when absent — never hard-coded per-site selectors.
    extraction_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Editorial classification (OFFICIAL / POLITICAL_MEDIA / MEDIA_OTHER),
    # assigned by an analyst/admin — independent of `reliability`.
    source_class: Mapped[str | None] = mapped_column(String(24), nullable=True)

    # Generic incremental cursor (e.g. last processed Telegram message_id).
    last_cursor: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # --- Telegram-specific (TELEGRAM_PUBLIC / TELEGRAM_PUBLIC_WEB) ---
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # pending | verified | failed | unsupported — never set to verified without
    # a real successful resolve.
    verification_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("uq_sources_url", "url", unique=True),
        Index("ix_sources_enabled", "enabled"),
    )

    @property
    def success_rate(self) -> float:
        return (self.success_count / self.total_runs) if self.total_runs else 0.0

    @property
    def health(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.total_runs == 0:
            return "pending"
        if self.consecutive_failures >= _FAILED_AFTER:
            return "failed"
        if self.consecutive_failures >= _DEGRADED_AFTER:
            return "degraded"
        return "healthy"


class CollectionRun(UUIDMixin, Base):
    __tablename__ = "collection_runs"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_versioned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    __table_args__ = (Index("ix_runs_source_started", "source_id", "started_at"),)


class RawArchive(UUIDMixin, Base):
    __tablename__ = "raw_archive"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Structured extraction result for WEBSITE items (title/author/body/images…).
    # The raw HTML is preserved in the object store (raw_ref); this is the parsed
    # view. Null for RSS items (whose raw JSON is already structured).
    extracted: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    http_headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Object-store key for the raw bytes (filesystem or MinIO backend).
    raw_ref: Mapped[str] = mapped_column(String(512), nullable=False)

    __table_args__ = (
        Index("ix_archive_content_hash", "content_hash"),
        Index("ix_archive_fingerprint", "fingerprint"),
        Index("ix_archive_source_extid", "source_id", "external_id"),
        Index("ix_archive_source_current", "source_id", "is_current"),
    )


RELATION_TYPES = ("same_event_candidate", "forwarded_from")


class ContentRelation(UUIDMixin, Base):
    """A non-destructive link between two archive items (e.g. the same event
    reported by different sources). We never delete or merge near-duplicates
    across sources — we record the relationship instead."""

    __tablename__ = "content_relations"

    from_archive_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_archive.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_archive_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_archive.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    similarity: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("uq_relation", "from_archive_id", "to_archive_id", "relation_type", unique=True),
    )


# --- Events (P1.6) ---
EVENT_STATUSES = ("pending", "confirmed", "dismissed", "closed")
EVENT_SEVERITIES = ("A", "B", "C", "D", "E", "F")


class Event(UUIDMixin, TimestampMixin, Base):
    """Analyst-created events linking archive items to structured incidents.

    Events are analyst-driven (no automatic extraction). They bridge P1 archive
    to P2 processing by allowing analysts to define and track incidents.
    """

    __tablename__ = "events"

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending"
    )
    severity: Mapped[str] = mapped_column(String(1), nullable=False, default="C")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_events_status", "status"),
        Index("ix_events_severity", "severity"),
        Index("ix_events_created_by", "created_by"),
    )


class EventArchive(Base):
    """Non-destructive analyst-driven link between an event and archive items.

    Separate from ContentRelation (which is data-level, about archive item
    relationships). EventArchive is analyst-level: "analyst linked this archive
    item to this event". CASCADE deletes events/archive, SET NULL on user deletion.
    """

    __tablename__ = "event_archive"

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )
    archive_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_archive.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    linked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    __table_args__ = (
        Index("ix_event_archive_linked_by", "linked_by"),
        Index("ix_event_archive_archive_id", "archive_id"),
    )


# --- Entities (P1.7) ---
ENTITY_TYPES = ("PERSON", "LOCATION", "ORGANIZATION", "VEHICLE", "PLACE", "OTHER")
ENTITY_STATUSES = ("pending", "confirmed", "dismissed", "archived")
ENTITY_RELATION_TYPES = ("same_as", "related_to", "parent_of", "child_of", "employed_by", "located_in", "affiliated_with")


class Entity(UUIDMixin, TimestampMixin, Base):
    """Analyst-created entities representing real-world intelligence items.

    Entities are analyst-driven (no automatic extraction). They connect to
    archive items and events via non-destructive linking.
    """

    __tablename__ = "entities"

    entity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending"
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_entities_status", "status"),
        Index("ix_entities_entity_type", "entity_type"),
        Index("ix_entities_created_by", "created_by"),
    )


class ArchiveEntity(Base):
    """Non-destructive analyst-driven link between an entity and archive items.

    Separate semantics from EntityRelationship: this is analyst-level linking
    of entities to raw archive data.
    """

    __tablename__ = "archive_entity"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )
    archive_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_archive.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    linked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    __table_args__ = (
        Index("ix_archive_entity_archive_id", "archive_id"),
        Index("ix_archive_entity_linked_by", "linked_by"),
    )


class EventEntity(Base):
    """Non-destructive analyst-driven link between an entity and events.

    Analyst-level: "this entity is involved in this event".
    """

    __tablename__ = "event_entity"

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    linked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    __table_args__ = (
        Index("ix_event_entity_event_id", "event_id"),
        Index("ix_event_entity_linked_by", "linked_by"),
    )


class EntityRelationship(UUIDMixin, Base):
    """Directed analyst-declared relationships between entities.

    Immutable after creation (no updates). Used for deduplication (same_as),
    connections (related_to, parent_of, etc.), and organizing the entity graph.
    Hard-delete only (no soft-delete); audit captures details before deletion.
    """

    __tablename__ = "entity_relationships"

    from_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_entity_relationship_to", "to_entity_id"),
        Index("ix_entity_relationship_type", "relation_type"),
        Index(
            "uq_entity_relationship",
            "from_entity_id",
            "to_entity_id",
            "relation_type",
            unique=True,
        ),
    )
